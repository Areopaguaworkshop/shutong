import { test, expect } from "bun:test"
import { DEFAULT_BACKEND_MODULE, DEFAULT_CORPUS_ROOT } from "../src/shared/constants"

test("core constants remain available to the plugin installer", () => {
  expect(DEFAULT_CORPUS_ROOT).toBe("corpus")
  expect(DEFAULT_BACKEND_MODULE).toBe("shutong_backend.rpc_server")
})
