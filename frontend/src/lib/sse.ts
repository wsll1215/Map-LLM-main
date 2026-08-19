export interface SseEventFrame {
  id: string;
  event: string;
  data: string;
}

export interface SseChunkResult {
  events: SseEventFrame[];
  remainder: string;
}

/** Parse complete SSE frames while retaining a partial final frame. */
export function consumeSseChunk(remainder: string, chunk: string): SseChunkResult {
  const combined = `${remainder}${chunk}`;
  const normalized = combined.replaceAll("\r\n", "\n").replaceAll("\r", "\n");
  const parts = normalized.split("\n\n");
  const incomplete = parts.pop() ?? "";
  const events: SseEventFrame[] = [];

  for (const part of parts) {
    if (!part.trim() || part.startsWith(":")) continue;
    let id = "";
    let event = "message";
    const data: string[] = [];
    for (const line of part.split("\n")) {
      if (line.startsWith("id:")) id = line.slice(3).trimStart();
      else if (line.startsWith("event:")) event = line.slice(6).trimStart();
      else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    events.push({ id, event, data: data.join("\n") });
  }

  return { events, remainder: incomplete };
}

export function parseJsonEvent<T = unknown>(frame: SseEventFrame): T {
  return JSON.parse(frame.data) as T;
}
