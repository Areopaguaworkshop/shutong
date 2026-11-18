import { serveStdio } from "@modelcontextprotocol/server/stdio";
import { createServer } from "./registry.ts";

serveStdio(createServer, { legacy: "serve" });
