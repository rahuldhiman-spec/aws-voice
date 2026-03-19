import { writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { compileFromFile } from "json-schema-to-typescript";

const currentDirectory = dirname(fileURLToPath(import.meta.url));
const contractsDirectory = join(currentDirectory, "..", "contracts");
const outputPath = join(contractsDirectory, "suva.ts");

const bannerComment = `/**
 * This file is auto-generated from the SUVA JSON Schemas.
 * Do not edit by hand. Run \`npm run generate:contracts\` after changing the schema files.
 */`;

const requestTypes = await compileFromFile(
  join(contractsDirectory, "suva-request.schema.json"),
  {
    bannerComment
  }
);
const responseTypes = await compileFromFile(
  join(contractsDirectory, "suva-response.schema.json"),
  {
    bannerComment: ""
  }
);

await writeFile(
  outputPath,
  `${requestTypes.trim()}\n\n${responseTypes.trim()}\n`
);
