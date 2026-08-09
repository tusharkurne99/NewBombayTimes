/* leaderboard.js — leaderboard storage, currently backed by localStorage
   (per-browser only, NOT shared across visitors -- see project plan).
   Deliberately isolated behind this small interface so swapping in a real
   shared backend (Firebase/Firestore) later means rewriting the inside of
   these three functions only -- callers (index.html, solve.html) never
   touch storage directly.

   puzzleId should be the puzzle's own "id" field (e.g. "2026-08-09-mini"),
   which already bakes in the date -- so the board naturally resets every
   day without any extra reset logic needed.
*/

(function () {
  var PREFIX = 'nbt_board_';

  function key(puzzleId) { return PREFIX + puzzleId; }

  function getBoard(puzzleId) {
    try {
      var raw = localStorage.getItem(key(puzzleId));
      var board = raw ? JSON.parse(raw) : [];
      board.sort(function (a, b) { return a.ms - b.ms; });
      return board;
    } catch (e) {
      return [];
    }
  }

  // Returns 1-based rank of the new entry.
  function submitTime(puzzleId, name, ms) {
    var board = getBoard(puzzleId);
    board.push({ name: name, ms: ms });
    board.sort(function (a, b) { return a.ms - b.ms; });
    try { localStorage.setItem(key(puzzleId), JSON.stringify(board)); } catch (e) { /* storage full/disabled -- non-fatal */ }
    for (var i = 0; i < board.length; i++) {
      if (board[i].name === name && board[i].ms === ms) return i + 1;
    }
    return board.length;
  }

  function formatTime(ms) {
    var s = Math.floor(ms / 1000);
    var m = Math.floor(s / 60); s = s % 60;
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  window.NBTLeaderboard = { getBoard: getBoard, submitTime: submitTime, formatTime: formatTime };
})();
