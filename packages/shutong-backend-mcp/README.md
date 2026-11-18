# shutong-backend-mcp

<!-- mcp-name: io.github.Areopaguaworkshop/shutong -->

PyPI launcher package for the [Shutong](https://github.com/Areopaguaworkshop/shutong)
MCP server.

The MCP Registry identifies a server by the package whose binary it launches.
`server.json` therefore names this distribution, `shutong-backend-mcp`, while the
implementation stays in `shutong-backend`. This package contains no server code:
it declares `shutong-backend==0.0.3` as an exact dependency and exposes the same
`shutong-backend-mcp` console script (`shutong_backend.mcp_server:cli`) that the
backend already ships.

## Usage

```bash
uvx shutong-backend-mcp
```

The server speaks stdio. Point it at a corpus with `SHUTONG_CORPUS_ROOT`.

## Prerequisite: citeindex

`shutong-backend` depends on `citeindex`, a separate upstream project on PyPI.
It brings paddlepaddle, mineru, whisperx, pyannote and playwright, so the first
install is about 13 GB and needs a network connection. Shutong does not vendor or
fork it; it is installed transitively.

## License

MIT.
