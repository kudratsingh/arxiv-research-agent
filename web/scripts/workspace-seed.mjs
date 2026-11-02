/** Produce the web dictionary from the direction kit; no taxonomy IDs invented. */
import fs from "node:fs";
const source = new URL("../../planning/11-daily-research-workspace/07-topic-seed.json", import.meta.url);
const target = new URL("../lib/daily/topics.json", import.meta.url);
const seed = JSON.parse(fs.readFileSync(source, "utf8"));
fs.writeFileSync(target, JSON.stringify({seedVersion: seed.seed_version, topics: seed.nodes.map(({id, label, kind, parent_ids}) => ({id, label, kind, parents: parent_ids}))}, null, 2) + "\n");
console.log(`Wrote ${seed.nodes.length} topics`);
