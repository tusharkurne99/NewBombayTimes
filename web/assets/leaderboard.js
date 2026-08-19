/* leaderboard.js — leaderboard storage, backed by Firestore (shared across
   every visitor). This is an ES module (loaded via <script type="module">)
   because it imports the Firebase SDK from a CDN -- everything else on
   this site is a plain classic script, this is the one exception.

   Same 3-function interface as the localStorage version it replaced
   (getBoard/submitTime/formatTime), so index.html/solve.html only needed
   to change in one way: these now return Promises instead of plain
   values, since a network write/read can't be synchronous. See the
   .then() usage at each call site.

   puzzleId should be the puzzle's own "id" field (e.g. "2026-08-09-mini"),
   which already bakes in the date -- so the board naturally resets every
   day without any extra reset logic needed.

   Security note (see docs/firestore.rules.txt): there are no user
   accounts on this site, so there's no auth to gate writes with. The
   Firestore rules are the actual server-side validation layer -- this
   file's job is just to shape the request correctly, not to be trusted
   as the only thing enforcing it (a browser console could call Firestore
   directly and skip this file entirely).
*/

import { initializeApp } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js";
import {
  getFirestore, collection, query, where, orderBy, limit,
  getDocs, addDoc, serverTimestamp,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-firestore.js";
import { firebaseConfig } from "./firebase-config.js";

const app = initializeApp(firebaseConfig);
const db = getFirestore(app);
const ENTRIES = "leaderboard_entries";
const BOARD_LIMIT = 50;

function formatTime(ms) {
  let s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60); s = s % 60;
  return m + ":" + (s < 10 ? "0" : "") + s;
}

// Returns a Promise<Array<{name, ms}>>, sorted fastest-first. Deliberately
// does NOT catch its own errors -- an earlier version did, returning []
// on any failure, which made "the query itself is broken" indistinguishable
// from "genuinely nobody has solved this yet." That's a real difference:
// one is a config problem to fix, the other is expected on a fresh board.
// Callers (solve.html, index.html) are the ones who decide how to show a
// failure, via .catch() -- see finishPuzzle()'s "Leaderboard unavailable
// right now" for the pattern.
//
// Note: this query (equality on puzzleId + orderBy ms) needs a Firestore
// composite index. The FIRST time this runs against a fresh project,
// Firestore rejects it with an error containing a direct "create this
// index" link -- click it once, wait ~a minute, and it works from then
// on. This is normal Firestore setup, not a bug -- but it WILL surface
// as a rejected promise now instead of silently, which is the point.
async function getBoard(puzzleId) {
  const q = query(
    collection(db, ENTRIES),
    where("puzzleId", "==", puzzleId),
    orderBy("ms", "asc"),
    limit(BOARD_LIMIT)
  );
  const snap = await getDocs(q);
  return snap.docs.map((d) => ({ id: d.id, name: d.data().name, ms: d.data().ms }));
}

// Writes a new entry, then returns a Promise<1-based rank>. Also does not
// swallow errors -- a write or read failure here should surface as a
// rejected promise, not silently report "rank 1" or "rank 0" as if it
// had actually succeeded.
async function submitTime(puzzleId, name, ms) {
  const docRef = await addDoc(collection(db, ENTRIES), {
    puzzleId,
    name: String(name).slice(0, 24),
    ms,
    at: serverTimestamp(),
  });
  const board = await getBoard(puzzleId);
  const idx = board.findIndex((row) => row.id === docRef.id);
  return idx === -1 ? board.length : idx + 1;
}

window.NBTLeaderboard = { getBoard, submitTime, formatTime };
