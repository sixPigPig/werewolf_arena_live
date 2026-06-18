import { apiFetch } from "./client";
import type { PlayerAvatarUploadResponse } from "../types";

export async function uploadPlayerAvatar(
  file: File,
): Promise<PlayerAvatarUploadResponse> {
  return apiFetch<PlayerAvatarUploadResponse>("/api/v1/player-profiles/avatar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: file.name,
      content_type: file.type,
      data_base64: await fileToBase64(file),
    }),
  });
}

async function fileToBase64(file: File) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  const chunks: string[] = [];
  const chunkSize = 0x8000;

  for (let index = 0; index < bytes.length; index += chunkSize) {
    chunks.push(String.fromCharCode(...bytes.subarray(index, index + chunkSize)));
  }

  return btoa(chunks.join(""));
}
