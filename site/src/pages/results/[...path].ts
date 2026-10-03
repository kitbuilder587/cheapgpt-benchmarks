import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import result from "../../../../results/index.json";

export const prerender = true;

export function getStaticPaths() {
  const paths = ["index.json", ...Object.keys(result.artifacts).map(
    (name) => `${result.manifest.run_id}/${name}`,
  )];
  return paths.map((path) => ({ params: { path }, props: { path } }));
}

export function GET({ props }: { props: { path: string } }) {
  const contentType = props.path.endsWith(".gz") ? "application/gzip"
    : props.path.endsWith(".html") ? "text/html; charset=utf-8"
    : props.path.endsWith(".jsonl") ? "application/x-ndjson; charset=utf-8"
    : "application/json; charset=utf-8";
  const content = readFileSync(resolve("../results", props.path));
  return new Response(new Uint8Array(content), {
    headers: { "Content-Type": contentType },
  });
}
