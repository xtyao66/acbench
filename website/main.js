const leaderboardRows = [
  {
    "agent": "OpenAI Code + Ops",
    "model": "gpt-4.1-mini",
    "code": 91.4,
    "ops": 72.7,
    "combined": 76.6,
    "scenarios": "61"
  },
  {
    "agent": "Claude Code + Ops",
    "model": "claude-sonnet-4-6",
    "code": 99.2,
    "ops": 78.5,
    "combined": 89.6,
    "scenarios": "61"
  },
  {
    "agent": "Gold Patch Baseline",
    "model": "reference",
    "code": 100,
    "ops": 100,
    "combined": 100,
    "scenarios": "54"
  }
];

// A null score means the mode was not evaluated; 0 is a real score.
function isPending(value) {
  return value === null || value === undefined;
}

function formatScore(value) {
  return isPending(value) ? "Pending" : value.toFixed(1);
}

function average(row) {
  const scores = [row.code, row.ops, row.combined].filter((value) => !isPending(value));
  return scores.length ? scores.reduce((sum, value) => sum + value, 0) / scores.length : null;
}

const body = document.querySelector("#leaderboard-body");

leaderboardRows
  .map((row) => ({ ...row, avg: average(row) }))
  // Rows with no evaluated mode sort last.
  .sort((a, b) => isPending(a.avg) - isPending(b.avg) || b.avg - a.avg)
  .forEach((row, index) => {
    const tr = document.createElement("tr");
    const pending = isPending(row.avg);

    tr.innerHTML = `
      <td>${index + 1}</td>
      <td><strong>${row.agent}</strong></td>
      <td>${row.model}</td>
      <td class="score">${formatScore(row.code)}</td>
      <td class="score">${formatScore(row.ops)}</td>
      <td class="score">${formatScore(row.combined)}</td>
      <td class="score">${pending ? '<span class="tag">Pending</span>' : row.avg.toFixed(1)}</td>
      <td>${row.scenarios}</td>
    `;
    body.appendChild(tr);
  });
