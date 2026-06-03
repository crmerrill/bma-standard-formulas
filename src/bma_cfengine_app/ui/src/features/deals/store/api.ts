import type { DealState } from "./session";

export type MergeConflictPayload = {
  entity_kind: string;
  entity_id: string;
  field_path: string;
  ours_value: unknown;
  theirs_value: unknown;
  ancestor_value: unknown;
};

export type MergeSuccess = { status: "success"; sha: string; diagnostic: null };
export type MergeConflict = {
  status: "conflict";
  sha: null;
  diagnostic: MergeConflictPayload;
};
export type MergeResult = MergeSuccess | MergeConflict;

export type CommitBody = {
  author: string;
  message: string;
  parent_sha: string;
  branch: string;
  payload: DealState;
  force?: boolean;
};

export class CommitConflictError extends Error {
  readonly head_sha: string;
  constructor(head_sha: string) {
    super("STALE_PARENT_SHA");
    this.name = "CommitConflictError";
    this.head_sha = head_sha;
  }
}

export async function commitToBranch(
  deal_id: string,
  body: CommitBody,
): Promise<{ sha: string }> {
  const res = await fetch(`/deals/${deal_id}/commit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.status === 409) {
    const data = (await res.json()) as {
      detail: { code: string; head_sha: string };
    };
    throw new CommitConflictError(data.detail.head_sha);
  }
  if (!res.ok) {
    throw new Error(`commitToBranch failed: ${res.status}`);
  }
  return res.json() as Promise<{ sha: string }>;
}

export async function mergeBranch(
  deal_id: string,
  body: { branch: string; into: string },
): Promise<MergeResult> {
  const res = await fetch(`/deals/${deal_id}/merge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`mergeBranch failed: ${res.status}`);
  }
  const response = (await res.json()) as {
    status: string;
    sha: unknown;
    diagnostic: unknown;
  };
  if (response.status === "success") {
    if (typeof response.sha !== "string") {
      throw new Error(
        "Protocol violation: success response missing sha string",
      );
    }
    return { status: "success", sha: response.sha, diagnostic: null };
  }
  if (response.status === "conflict") {
    if (response.diagnostic == null) {
      throw new Error(
        "Protocol violation: conflict response missing diagnostic",
      );
    }
    return {
      status: "conflict",
      sha: null,
      diagnostic: response.diagnostic as MergeConflictPayload,
    };
  }
  throw new Error(`mergeBranch: unexpected status "${response.status}"`);
}

export async function deleteBranch(
  deal_id: string,
  branch_name: string,
): Promise<void> {
  const res = await fetch(`/deals/${deal_id}/branches/${branch_name}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(`deleteBranch failed: ${res.status}`);
  }
}
