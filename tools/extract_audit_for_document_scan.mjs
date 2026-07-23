import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const [inputPath, outputPath] = process.argv.slice(2);
if (!inputPath || !outputPath) {
  throw new Error("Uso: node extract_audit_for_document_scan.mjs <auditoria.xlsx> <saida.json>");
}

const input = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const sheet = workbook.worksheets.getItem("Lançamentos");
const values = sheet.getUsedRange(true).values;
const headers = values[0].map((value) => String(value ?? ""));
const column = (label) => {
  const index = headers.indexOf(label);
  if (index < 0) throw new Error(`Coluna ausente: ${label}`);
  return index;
};
const columns = {
  transactionId: column("ID do lançamento"),
  date: column("Data"),
  description: column("Descrição"),
  amount: column("Valor"),
  type: column("Tipo"),
  account: column("Conta"),
  importId: column("ID lote de importação"),
  sourceFilename: column("Arquivo de origem"),
  sourceHash: column("Hash SHA-1 do arquivo"),
  sourceBank: column("Banco detectado"),
  sourceKind: column("Natureza da fonte"),
  storedId: column("ID documento no cofre"),
  storedFilename: column("Documento no cofre"),
};

function excelDate(value) {
  if (typeof value !== "number") return String(value ?? "").slice(0, 10);
  const millis = Math.round((value - 25569) * 86400 * 1000);
  return new Date(millis).toISOString().slice(0, 10);
}

const rows = values.slice(1).map((row) => ({
  transaction_id: row[columns.transactionId] ?? "",
  date: excelDate(row[columns.date]),
  description: String(row[columns.description] ?? ""),
  amount: Number(row[columns.amount] ?? 0),
  type: String(row[columns.type] ?? ""),
  account: String(row[columns.account] ?? ""),
  imported_file_id: String(row[columns.importId] ?? ""),
  source_filename: String(row[columns.sourceFilename] ?? ""),
  source_hash: String(row[columns.sourceHash] ?? "").toLowerCase(),
  source_bank: String(row[columns.sourceBank] ?? ""),
  source_kind: String(row[columns.sourceKind] ?? ""),
  stored_document_id: String(row[columns.storedId] ?? ""),
  stored_document_filename: String(row[columns.storedFilename] ?? ""),
}));

const documents = {};
for (const row of rows) {
  if (!row.source_hash) continue;
  const item = documents[row.source_hash] ?? {
    sha1: row.source_hash,
    source_filenames: [],
    imported_file_ids: [],
    accounts: [],
    banks: [],
    source_kinds: [],
    transaction_count: 0,
    stored_transaction_count: 0,
  };
  for (const [key, value] of [
    ["source_filenames", row.source_filename],
    ["imported_file_ids", row.imported_file_id],
    ["accounts", row.account],
    ["banks", row.source_bank],
    ["source_kinds", row.source_kind],
  ]) {
    if (value && !item[key].includes(value)) item[key].push(value);
  }
  item.transaction_count += 1;
  if (row.stored_document_id) item.stored_transaction_count += 1;
  documents[row.source_hash] = item;
}

await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.writeFile(
  outputPath,
  JSON.stringify(
    {
      source_workbook: inputPath,
      transaction_count: rows.length,
      distinct_document_hashes: Object.keys(documents).length,
      documents,
      transactions: rows,
    },
    null,
    2,
  ),
  "utf8",
);
process.stdout.write(
  JSON.stringify({
    transactions: rows.length,
    distinct_document_hashes: Object.keys(documents).length,
    output: outputPath,
  }) + "\n",
);
