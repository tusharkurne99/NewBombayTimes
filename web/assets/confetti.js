/* confetti.js — lightweight canvas particle burst, no external libraries
   (Artifact/CSP-style constraint carried over deliberately: no CDN
   dependency for something this small). Shared by index.html (design
   preview button) and solve.html (real top-5 celebration). */

(function () {
  var canvas, ctx;
  var COLORS = ['#3454d1', '#b8892b', '#a06a3c', '#14110d', '#8a8577'];

  function ensureCanvas() {
    if (canvas) return;
    canvas = document.getElementById('confetti-canvas');
    if (!canvas) return;
    ctx = canvas.getContext('2d');
    function resize() { canvas.width = innerWidth; canvas.height = innerHeight; }
    resize();
    window.addEventListener('resize', resize);
  }

  function burstConfetti(originX, originY) {
    ensureCanvas();
    if (!ctx) return;
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    var particles = [];
    var count = 90;
    for (var i = 0; i < count; i++) {
      var angle = Math.random() * Math.PI * 2;
      var speed = 3 + Math.random() * 6;
      particles.push({
        x: originX, y: originY,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed - 3,
        size: 4 + Math.random() * 4,
        color: COLORS[i % COLORS.length],
        rot: Math.random() * Math.PI,
        vr: (Math.random() - .5) * 0.3
      });
    }
    var start = null;
    function frame(ts) {
      if (!start) start = ts;
      var elapsed = ts - start;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      particles.forEach(function (p) {
        p.vy += 0.12;
        p.x += p.vx;
        p.y += p.vy;
        p.rot += p.vr;
        ctx.save();
        ctx.translate(p.x, p.y);
        ctx.rotate(p.rot);
        ctx.fillStyle = p.color;
        ctx.globalAlpha = Math.max(0, 1 - elapsed / 1800);
        ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size * 0.6);
        ctx.restore();
      });
      if (elapsed < 1800) requestAnimationFrame(frame);
      else ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
    requestAnimationFrame(frame);
  }

  window.NBTConfetti = { burst: burstConfetti };
})();
