/**
 * facechain SAS sidecar: Solana Attestation Service glue for the Python CLI.
 *
 * One JSON command on stdin, one JSON result on stdout; on failure `{"error": "..."}` and exit
 * code 1. Runs directly on Node >= 22.6 through type stripping: `node chain-ts/sas.ts`.
 *
 * Commands
 *   {"cmd":"setup","keypair":PATH,"rpc":URL}
 *     -> {"credential":PDA,"schema":PDA,"authority":ADDR,"txs":[SIG,...],"created":{...}}
 *   {"cmd":"attest","keypair","rpc","credential","schema","bundle_hash","cid","post_url",
 *    "similarity_bps","expiry"}
 *     -> {"attestation":PDA,"signature":SIG|null,"nonce":ADDR,"existed":bool}
 *   {"cmd":"fetch","rpc","credential","schema","bundle_hash"}
 *     -> {"found":true,"attestation":PDA,"nonce":ADDR,"signer":ADDR,"expiry":0,"data":{...}}
 *      | {"found":false,"attestation":PDA,"nonce":ADDR}
 *
 * The attestation nonce is the 32 bytes of the bundle hash read as an address, so anyone holding
 * the bundle can derive the attestation PDA ["attestation", credential, schema, nonce] without a
 * receipt. The SPL memo stays a separate transaction sent from Python; this file never imports
 * the memo program. The keypair bytes are never logged or echoed.
 */

import { readFileSync } from "node:fs";
import { text } from "node:stream/consumers";

import {
  appendTransactionMessageInstructions,
  createKeyPairSignerFromBytes,
  createSolanaRpc,
  createTransactionMessage,
  getAddressDecoder,
  getSignatureFromTransaction,
  isAddress,
  pipe,
  sendTransactionWithoutConfirmingFactory,
  setTransactionMessageFeePayerSigner,
  setTransactionMessageLifetimeUsingBlockhash,
  signTransactionMessageWithSigners,
  type Address,
  type Instruction,
  type KeyPairSigner,
  type Signature,
} from "@solana/kit";
import {
  deriveAttestationPda,
  deriveCredentialPda,
  deriveSchemaPda,
  deserializeAttestationData,
  fetchMaybeAttestation,
  fetchMaybeCredential,
  fetchMaybeSchema,
  getCreateAttestationInstruction,
  getCreateCredentialInstruction,
  getCreateSchemaInstruction,
  serializeAttestationData,
  SOLANA_ATTESTATION_SERVICE_PROGRAM_ADDRESS,
  type Schema,
} from "sas-lib";

const CREDENTIAL_NAME = "FACECHAIN";
const SCHEMA_NAME = "FaceMatchV1";
const SCHEMA_VERSION = 1;
const SCHEMA_DESCRIPTION = "facechain face-match evidence record";
// SAS compact layout codes: 12 = String, 3 = U64 (see sas-lib utils.ts).
const SCHEMA_LAYOUT = [12, 12, 12, 3] as const;
const SCHEMA_FIELDS = ["bundle_hash", "cid", "post_url", "similarity_bps"] as const;
const CONFIRM_TIMEOUT_MS = 90_000;
const POLL_INTERVAL_MS = 1_500;

type Json = Record<string, unknown>;
type SasRpc = ReturnType<typeof createSolanaRpc>;

class SidecarError extends Error {}

// -- input helpers ----------------------------------------------------------------------
function str(input: Json, key: string, allowEmpty = false): string {
  const value = input[key];
  if (typeof value !== "string" || (!allowEmpty && value.length === 0)) {
    throw new SidecarError(`missing or invalid "${key}"`);
  }
  return value;
}

function addr(input: Json, key: string): Address {
  const value = str(input, key);
  if (!isAddress(value)) {
    throw new SidecarError(`"${key}" is not a valid Solana address`);
  }
  return value;
}

function uint(input: Json, key: string, fallback?: number): number {
  const value = input[key] ?? fallback;
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new SidecarError(`"${key}" must be a non-negative integer`);
  }
  return value;
}

/** The 32-byte bundle hash, read verbatim as an address: the deterministic attestation nonce. */
function nonceFromBundleHash(hex: string): Address {
  if (!/^[0-9a-f]{64}$/.test(hex)) {
    throw new SidecarError('"bundle_hash" must be 64 lowercase hex characters');
  }
  return getAddressDecoder().decode(Uint8Array.from(Buffer.from(hex, "hex")));
}

async function loadSigner(path: string): Promise<KeyPairSigner> {
  let raw: unknown;
  try {
    raw = JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    throw new SidecarError(`cannot read keypair file ${path}: ${(error as Error).message}`);
  }
  const bytes = Array.isArray(raw) ? raw : [];
  if (bytes.length !== 64 || !bytes.every((b) => Number.isInteger(b) && b >= 0 && b < 256)) {
    throw new SidecarError(`keypair file ${path} is not a 64-byte JSON array`);
  }
  return createKeyPairSignerFromBytes(Uint8Array.from(bytes as number[]));
}

// -- schema shape -----------------------------------------------------------------------
/** Schema.fieldNames is stored as concatenated u32-length-prefixed strings. */
function decodeFieldNames(bytes: Uint8Array): string[] {
  const names: string[] = [];
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const decoder = new TextDecoder();
  let offset = 0;
  while (offset + 4 <= bytes.length) {
    const length = view.getUint32(offset, true);
    offset += 4;
    names.push(decoder.decode(bytes.subarray(offset, offset + length)));
    offset += length;
  }
  return names;
}

function assertSchemaShape(schema: Schema, address: Address): void {
  const layout = Array.from(schema.layout);
  const names = decodeFieldNames(Uint8Array.from(schema.fieldNames));
  const sameLayout =
    layout.length === SCHEMA_LAYOUT.length && layout.every((v, i) => v === SCHEMA_LAYOUT[i]);
  const sameNames =
    names.length === SCHEMA_FIELDS.length && names.every((v, i) => v === SCHEMA_FIELDS[i]);
  if (!sameLayout || !sameNames) {
    throw new SidecarError(
      `schema ${address} has layout [${layout}] fields [${names}]; ` +
        `expected [${SCHEMA_LAYOUT}] [${SCHEMA_FIELDS}]`,
    );
  }
}

// -- transactions -----------------------------------------------------------------------
async function waitForConfirmation(rpc: SasRpc, signature: Signature): Promise<void> {
  const deadline = Date.now() + CONFIRM_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const { value } = await rpc.getSignatureStatuses([signature]).send();
    const status = value[0];
    if (status) {
      if (status.err !== null) {
        throw new SidecarError(`transaction ${signature} failed: ${JSON.stringify(status.err)}`);
      }
      if (status.confirmationStatus === "confirmed" || status.confirmationStatus === "finalized") {
        return;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
  }
  throw new SidecarError(
    `timed out after ${CONFIRM_TIMEOUT_MS / 1000}s waiting for ${signature} to confirm`,
  );
}

async function sendInstructions(
  rpc: SasRpc,
  signer: KeyPairSigner,
  instructions: readonly Instruction[],
): Promise<Signature> {
  const { value: latestBlockhash } = await rpc.getLatestBlockhash({ commitment: "confirmed" }).send();
  const message = pipe(
    createTransactionMessage({ version: 0 }),
    (m) => setTransactionMessageFeePayerSigner(signer, m),
    (m) => setTransactionMessageLifetimeUsingBlockhash(latestBlockhash, m),
    (m) => appendTransactionMessageInstructions(instructions, m),
  );
  const transaction = await signTransactionMessageWithSigners(message);
  const signature = getSignatureFromTransaction(transaction);
  await sendTransactionWithoutConfirmingFactory({ rpc })(transaction, { commitment: "confirmed" });
  await waitForConfirmation(rpc, signature);
  return signature;
}

// -- commands ---------------------------------------------------------------------------
async function setup(input: Json): Promise<Json> {
  const rpc = createSolanaRpc(str(input, "rpc"));
  const signer = await loadSigner(str(input, "keypair"));
  const [credential] = await deriveCredentialPda({
    authority: signer.address,
    name: CREDENTIAL_NAME,
  });
  const [schema] = await deriveSchemaPda({
    credential,
    name: SCHEMA_NAME,
    version: SCHEMA_VERSION,
  });
  const txs: Signature[] = [];
  const created = { credential: false, schema: false };

  const existingCredential = await fetchMaybeCredential(rpc, credential);
  if (!existingCredential.exists) {
    const instruction = getCreateCredentialInstruction({
      payer: signer,
      credential,
      authority: signer,
      name: CREDENTIAL_NAME,
      signers: [signer.address],
    });
    txs.push(await sendInstructions(rpc, signer, [instruction]));
    created.credential = true;
  }

  const existingSchema = await fetchMaybeSchema(rpc, schema);
  if (!existingSchema.exists) {
    const instruction = getCreateSchemaInstruction({
      payer: signer,
      authority: signer,
      credential,
      schema,
      name: SCHEMA_NAME,
      description: SCHEMA_DESCRIPTION,
      layout: Uint8Array.from(SCHEMA_LAYOUT),
      fieldNames: [...SCHEMA_FIELDS],
    });
    txs.push(await sendInstructions(rpc, signer, [instruction]));
    created.schema = true;
  } else {
    assertSchemaShape(existingSchema.data, schema);
  }

  return {
    credential,
    schema,
    authority: signer.address,
    program: SOLANA_ATTESTATION_SERVICE_PROGRAM_ADDRESS,
    txs,
    created,
  };
}

async function attest(input: Json): Promise<Json> {
  const rpc = createSolanaRpc(str(input, "rpc"));
  const signer = await loadSigner(str(input, "keypair"));
  const credential = addr(input, "credential");
  const schema = addr(input, "schema");
  const bundleHash = str(input, "bundle_hash");
  const nonce = nonceFromBundleHash(bundleHash);
  const record = {
    bundle_hash: bundleHash,
    cid: str(input, "cid", true),
    post_url: str(input, "post_url", true),
    similarity_bps: uint(input, "similarity_bps"),
  };
  const expiry = uint(input, "expiry", 0);

  const [attestation] = await deriveAttestationPda({ credential, schema, nonce });
  const existing = await fetchMaybeAttestation(rpc, attestation);
  if (existing.exists) {
    return { attestation, signature: null, nonce, existed: true };
  }
  const schemaAccount = await fetchMaybeSchema(rpc, schema);
  if (!schemaAccount.exists) {
    throw new SidecarError(`schema ${schema} does not exist; run setup first`);
  }
  assertSchemaShape(schemaAccount.data, schema);
  const data = serializeAttestationData(schemaAccount.data, record);
  const instruction = getCreateAttestationInstruction({
    payer: signer,
    authority: signer,
    credential,
    schema,
    attestation,
    nonce,
    data,
    expiry,
  });
  const signature = await sendInstructions(rpc, signer, [instruction]);
  return { attestation, signature, nonce, existed: false };
}

async function fetchRecord(input: Json): Promise<Json> {
  const rpc = createSolanaRpc(str(input, "rpc"));
  const credential = addr(input, "credential");
  const schema = addr(input, "schema");
  const nonce = nonceFromBundleHash(str(input, "bundle_hash"));
  const [attestation] = await deriveAttestationPda({ credential, schema, nonce });
  const account = await fetchMaybeAttestation(rpc, attestation);
  if (!account.exists) {
    return { found: false, attestation, nonce };
  }
  const schemaAccount = await fetchMaybeSchema(rpc, schema);
  if (!schemaAccount.exists) {
    throw new SidecarError(`schema ${schema} does not exist`);
  }
  const decoded = deserializeAttestationData<Record<string, unknown>>(
    schemaAccount.data,
    Uint8Array.from(account.data.data),
  );
  return {
    found: true,
    attestation,
    nonce,
    signer: account.data.signer,
    credential: account.data.credential,
    schema: account.data.schema,
    expiry: Number(account.data.expiry),
    data: {
      bundle_hash: String(decoded.bundle_hash),
      cid: String(decoded.cid),
      post_url: String(decoded.post_url),
      similarity_bps: Number(decoded.similarity_bps),
    },
  };
}

// -- entry point ------------------------------------------------------------------------
const COMMANDS: Record<string, (input: Json) => Promise<Json>> = {
  setup,
  attest,
  fetch: fetchRecord,
};

function describeError(error: unknown): string {
  if (error instanceof SidecarError) {
    return error.message;
  }
  if (error instanceof Error) {
    const context = (error as { context?: { logs?: unknown } }).context;
    const logs = Array.isArray(context?.logs) ? `\n${context.logs.join("\n")}` : "";
    const cause = error.cause instanceof Error ? ` (cause: ${error.cause.message})` : "";
    return `${error.message}${cause}${logs}`;
  }
  return String(error);
}

async function main(): Promise<void> {
  const raw = (await text(process.stdin)).trim();
  if (raw.length === 0) {
    throw new SidecarError("expected a JSON command on stdin");
  }
  let input: Json;
  try {
    input = JSON.parse(raw) as Json;
  } catch {
    throw new SidecarError("stdin is not valid JSON");
  }
  const cmd = str(input, "cmd");
  const handler = COMMANDS[cmd];
  if (handler === undefined) {
    throw new SidecarError(`unknown cmd "${cmd}" (expected setup, attest or fetch)`);
  }
  const result = await handler(input);
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

main().catch((error: unknown) => {
  process.stdout.write(`${JSON.stringify({ error: describeError(error) })}\n`);
  process.exitCode = 1;
});
