// firebase-config.js — real config for the "new-bombay-times" Firebase
// project. Safe to commit/expose client-side -- it's not a secret.
// Firebase's actual access control is enforced by Firestore security
// rules (see docs/firestore.rules.txt), not by hiding this config.
//
// measurementId/Analytics deliberately omitted -- this site only uses
// Firestore (the leaderboard), no Analytics SDK is loaded.
export const firebaseConfig = {
  apiKey: "AIzaSyDBLxg5CSd2e-BWpAYPnhEJ64Vo__7_r6Q",
  authDomain: "new-bombay-times.firebaseapp.com",
  projectId: "new-bombay-times",
  storageBucket: "new-bombay-times.firebasestorage.app",
  messagingSenderId: "33509443851",
  appId: "1:33509443851:web:11c1360d1ba414a996fa0e",
};
