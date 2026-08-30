export function subscriptionNeedsRefresh(
  connectedRequestIds: ReadonlySet<number>,
  requestedRequestIds: Iterable<number>,
): boolean {
  const requested = [...requestedRequestIds];
  return requested.length !== connectedRequestIds.size || requested.some((id) => !connectedRequestIds.has(id));
}

export function isCursorAfter(candidate: string, current: string): boolean {
  if (!current) return Boolean(candidate);
  if (!candidate) return false;
  const [candidateMajor, candidateMinor = 0] = candidate.split("-").map(Number);
  const [currentMajor, currentMinor = 0] = current.split("-").map(Number);
  if (![candidateMajor, candidateMinor, currentMajor, currentMinor].every(Number.isFinite)) return false;
  return candidateMajor > currentMajor || (candidateMajor === currentMajor && candidateMinor > currentMinor);
}
