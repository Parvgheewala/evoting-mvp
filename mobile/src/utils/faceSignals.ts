/**
 * mobile/src/utils/faceSignals.ts
 *
 * Converts a MediaPipe Face Mesh 468-point landmark array into a FrameData
 * object suitable for the liveness frame buffer.
 *
 * These functions mirror the HTML engine (FaceProcessor.html) exactly so
 * that any signal computed in the WebView can be reproduced or audited
 * in TypeScript.
 *
 * Landmark index reference:
 *   https://developers.google.com/mediapipe/solutions/vision/face_landmarker
 */

import type { FrameData } from "../components/LivenessCamera";

// ── Landmark type ─────────────────────────────────────────────────────────

/** Single 3-D landmark point from MediaPipe (x, y, z all normalised 0–1). */
export type Landmark = {
  x: number;
  y: number;
  z: number;
};

// ── Distance helper ───────────────────────────────────────────────────────

/**
 * Euclidean distance between two 2-D landmark points.
 * z is intentionally ignored — 2-D is sufficient for EAR and smile.
 */
export const dist = (a: Landmark, b: Landmark): number =>
  Math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2);

// ── Eye Aspect Ratio ──────────────────────────────────────────────────────

/**
 * MediaPipe landmark indices for the left and right eyes.
 * Order: [outer, upper-inner-1, upper-inner-2, inner, lower-inner-1, lower-inner-2]
 * This matches the EAR formula: (dist(p2,p6) + dist(p3,p5)) / (2 * dist(p1,p4))
 */
export const LEFT_EYE_IDX:  number[] = [33,  160, 158, 133, 153, 144];
export const RIGHT_EYE_IDX: number[] = [362, 385, 387, 263, 373, 380];

/**
 * Eye Aspect Ratio (EAR).
 *
 * Formula from Soukupová & Čech (2016), adapted for normalised coordinates:
 *   EAR = (dist(p2, p6) + dist(p3, p5)) / (2 × dist(p1, p4))
 *
 * Returns a value in [0, ~0.5]:
 *   • Open eye  → ~0.25–0.45
 *   • Blink     → < 0.3  (transition to ~0.05–0.15 at full closure)
 *
 * @param lm      Full 468-landmark array from MediaPipe.
 * @param indices 6 landmark indices for the eye (see LEFT_EYE_IDX / RIGHT_EYE_IDX).
 */
export function computeEAR(lm: Landmark[], indices: number[]): number {
  const [p1, p2, p3, p4, p5, p6] = indices.map((i) => lm[i]);

  const numerator   = dist(p2, p6) + dist(p3, p5);
  const denominator = 2 * dist(p1, p4);

  // Guard against degenerate cases (e.g. partially occluded eye)
  if (denominator === 0) return 0;

  return numerator / denominator;
}

// ── Head Pose — Yaw ───────────────────────────────────────────────────────

/**
 * Yaw estimation — head horizontal rotation.
 *
 * Uses the horizontal offset of the nose tip (lm[1]) from the midpoint
 * between the left (lm[234]) and right (lm[454]) cheekbone landmarks.
 *
 * Returns a value scaled to approximate degrees:
 *   •  0       → looking straight ahead
 *   • < -20    → turned left  (turn_head_left challenge threshold)
 *   • > +20    → turned right (turn_head_right challenge threshold)
 *
 * Multiply by 200 converts normalised offset to a degrees-like range.
 */
export function computeYaw(lm: Landmark[]): number {
  const nose  = lm[1];
  const left  = lm[234];
  const right = lm[454];

  const midX = (left.x + right.x) / 2;
  return (nose.x - midX) * 200;
}

// ── Head Pose — Pitch ─────────────────────────────────────────────────────

/**
 * Pitch estimation — head vertical rotation (nod).
 *
 * Uses the vertical distance between forehead (lm[10]) and chin (lm[152]).
 * When the head nods down, chin.y increases relative to forehead.y
 * and the value grows positively; nodding up shrinks it.
 *
 * The nod challenge requires pitch to oscillate by ±15° (≥30° total swing).
 */
export function computePitch(lm: Landmark[]): number {
  const forehead = lm[10];
  const chin     = lm[152];
  return (chin.y - forehead.y) * 200;
}

// ── Smile Score ───────────────────────────────────────────────────────────

/**
 * Smile score — distance between left (lm[61]) and right (lm[291]) lip corners.
 *
 * A neutral face has a smaller inter-corner distance.
 * A smile widens the mouth, increasing this value.
 * The backend expects smileScore > 0.7 for the smile challenge.
 *
 * Note: the raw distance is in normalised [0,1] space. Typical values:
 *   • Neutral → ~0.03–0.06
 *   • Smile   → ~0.07–0.12
 * Multiply by 10 to bring into the expected [0, 1] backend range.
 */
export function computeSmile(lm: Landmark[]): number {
  return dist(lm[61], lm[291]) * 10;
}

// ── Full Conversion ───────────────────────────────────────────────────────

/**
 * Convert a MediaPipe 468-point landmark array into a FrameData object.
 *
 * This is the single source of truth for landmark → signal conversion.
 * The HTML engine (FaceProcessor.html) duplicates this logic in plain JS
 * so it can run inside the WebView without a bundler.
 *
 * @param lm  Array of 468 Landmark objects from MediaPipe Face Mesh.
 * @returns   FrameData ready to push into the liveness frame buffer.
 */
export function convertLandmarksToFrame(lm: Landmark[]): FrameData {
  return {
    leftEyeOpen:  computeEAR(lm, LEFT_EYE_IDX),
    rightEyeOpen: computeEAR(lm, RIGHT_EYE_IDX),
    yaw:          computeYaw(lm),
    pitch:        computePitch(lm),
    smileScore:   computeSmile(lm),
    timestamp:    Date.now(),
  };
}

// ── Frame Validation ──────────────────────────────────────────────────────

/**
 * Quick sanity check before pushing a frame into the buffer.
 * Rejects frames with missing or NaN signal values.
 *
 * @returns true if the frame is valid and should be buffered.
 */
export function isValidFrame(frame: Partial<FrameData>): frame is FrameData {
  return (
    typeof frame.leftEyeOpen  === "number" && !isNaN(frame.leftEyeOpen)  &&
    typeof frame.rightEyeOpen === "number" && !isNaN(frame.rightEyeOpen) &&
    typeof frame.yaw          === "number" && !isNaN(frame.yaw)          &&
    typeof frame.pitch        === "number" && !isNaN(frame.pitch)        &&
    typeof frame.timestamp    === "number" && frame.timestamp > 0
  );
}