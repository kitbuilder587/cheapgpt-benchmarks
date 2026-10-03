import index from "../../../../official/index.json";

export const prerender = true;

export function GET() {
  return new Response(JSON.stringify(index), {
    headers: {
      "Cache-Control": "public, max-age=300",
      "Content-Type": "application/json; charset=utf-8",
    },
  });
}
