import OpenAI from "openai";

const SYSTEM = `
You are the team's production assistant.
Every clinical or policy claim must end with a source tag:
- [SOURCE: Document "<exact title>"]
- [SOURCE: Unknown]
Never invent a document title.

When the user asks for identifier DOC-104, quote it exactly.
`;

export async function complete(user: string): Promise<string> {
  const client = new OpenAI({ apiKey: process.env.OPENROUTER_API_KEY });
  const model = process.env.OPENROUTER_MODEL || "openai/gpt-4o-mini";
  const res = await client.chat.completions.create({
    model,
    messages: [
      { role: "system", content: SYSTEM },
      { role: "user", content: user },
    ],
  });
  return res.choices[0]?.message?.content || "";
}
