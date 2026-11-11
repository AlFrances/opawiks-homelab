// Draws the hub diagram: the homelab in the middle, linked to each collection.
const hub = document.getElementById("hub");
const center = 300;
const collections = [
  { name: "Photos", href: "photos/", angle: -90 },
  { name: "ROMs", href: "roms/", angle: 30 },
  { name: "Movies", href: "movies/", angle: 150 },
];

// Turns an angle and distance from the middle into x and y positions.
function point(angle, distance) {
  const radians = (angle * Math.PI) / 180;
  return [center + distance * Math.cos(radians), center + distance * Math.sin(radians)];
}

let ticks = "";
for (let angle = 0; angle < 360; angle += 3) {
  const length = angle % 30 === 0 ? 16 : 7;
  const [x1, y1] = point(angle, 288);
  const [x2, y2] = point(angle, 288 - length);
  ticks += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/>`;
}

let spokes = "";
let nodes = "";
for (const { name, href, angle } of collections) {
  const [startX, startY] = point(angle, 72);
  const [x, y] = point(angle, 190);
  // The top label sits above its marker so the line doesn't run through the word.
  const labelOffset = angle === -90 ? -24 : 45;
  spokes += `<line class="spoke draw" pathLength="1" x1="${startX}" y1="${startY}" x2="${x}" y2="${y}"/>`;
  nodes += `<a href="${href}" aria-label="Open ${name}">
    <circle class="hit" cx="${x}" cy="${y + labelOffset / 2}" r="58"/>
    <rect class="node-mark" x="${x - 9}" y="${y - 9}" width="18" height="18" transform="rotate(45 ${x} ${y})"/>
    <text class="node-label" x="${x}" y="${y + labelOffset}">${name}</text>
  </a>`;
}

hub.innerHTML = `
  <circle class="ring ring-accent draw" pathLength="1" cx="${center}" cy="${center}" r="262"/>
  <g class="ticks">${ticks}</g>
  <circle class="ring draw" pathLength="1" cx="${center}" cy="${center}" r="190"/>
  ${spokes}
  <circle class="ring ring-accent draw" pathLength="1" cx="${center}" cy="${center}" r="72"/>
  <text class="hub-name" x="${center}" y="${center + 9}">Opawiks</text>
  ${nodes}`;

// If the browser restores this page from memory (back button), reload it so the
// server sees the visit and ends the login.
window.addEventListener("pageshow", (event) => {
  if (event.persisted) {
    location.reload();
  }
});
