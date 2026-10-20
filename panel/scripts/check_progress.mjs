function progressCell(state, stepId, cellCount = 5) {
  const last = cellCount - 1;
  switch (state) {
    case "queued":
      return { index: 0, pose: "idle" };
    case "awaiting_approval":
      return { index: Math.min(2, last), pose: "pause" };
    case "succeeded":
      return { index: last, pose: "win" };
    case "failed":
    case "cancelled":
      return { index: Math.min(3, last), pose: "fail" };
    case "running": {
      const stepNum = stepId?.match(/(\d+)/)?.[1];
      const n = stepNum ? Number(stepNum) : 1;
      const idx = Math.min(Math.max(n, 1), last - 1);
      return { index: idx, pose: "run" };
    }
    default:
      return { index: 0, pose: "idle" };
  }
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

assert(progressCell("queued", null).index === 0, "queued");
assert(progressCell("running", "step2").pose === "run", "running pose");
assert(progressCell("running", "step2").index === 2, "running step2");
assert(progressCell("succeeded", "step2").pose === "win", "win");
assert(progressCell("failed", "step1").pose === "fail", "fail");
console.log("progressCell ok");
