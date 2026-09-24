// Produce metro-symbolicate's answers for the symbolicate tests.
//
//   node golden.js <metro-symbolicate dir> <spec.json> <out.json>
//
// spec: {"stacks": [{"id", "map", "stacks": <[{id, text}] file>, "inputColumnStart"?}],
//        "positions": [{"id", "map", "points": [[line, col], ...]}],
//        "crashes": [{"id", "map", "callstack": [...]}]}
// Paths in the spec are relative to the spec file.
//
// For stacks this runs the metro-symbolicate CLI itself (stdin form) and,
// frame by frame, the same regex and lookup it uses, recording the full
// position (the CLI prints only file:line:name). Every record is checked to
// rebuild the CLI's output exactly, so the details are what the CLI computed.
//
// Output, one entry per line: each stack's `lines` align with its text split
// on "\n"; each line lists what the regex matched in it as
// [fileName, line, column, source, origLine, origColumn, name, functionName,
//  identifierName, isIgnored], where name is what the CLI prints.
// Positions list [line, column, source, origLine, origColumn, name,
// functionName, identifierName]. Crashes keep the CLI's JSON as it is.
'use strict';
const fs = require('fs');
const path = require('path');
const {execFileSync} = require('child_process');

const [, , metroDir, specPath, outPath] = process.argv;
const Symbolication = require(path.join(metroDir, 'src/Symbolication.js'));
const {SourceMapConsumer} = require(path.join(metroDir, 'node_modules/source-map'));
const cli = path.join(metroDir, 'src/index.js');
const spec = JSON.parse(fs.readFileSync(specPath, 'utf8'));
const base = path.dirname(specPath);
const contexts = new Map();

function context(mapFile, inputColumnStart) {
  const key = mapFile + '|' + inputColumnStart;
  if (!contexts.has(key)) {
    contexts.set(key, Symbolication.createContext(
      SourceMapConsumer, fs.readFileSync(path.join(base, mapFile), 'utf8'),
      {inputColumnStart}));
  }
  return contexts.get(key);
}

// Symbolication.js's own pattern, from SymbolicationContext.symbolicate.
const RE = /(?:([^@: \n(]+)(@|:))?(?:(?:([^@: \n(]+):)?(\d+):(\d+)|\[native code\])/g;

const out = {stacks: [], positions: [], crashes: []};
const stackCases = [];
for (const group of spec.stacks || []) {
  for (const st of JSON.parse(fs.readFileSync(path.join(base, group.stacks), 'utf8'))) {
    stackCases.push({id: group.id + '/' + st.id, map: group.map, text: st.text,
      inputColumnStart: group.inputColumnStart});
  }
}
for (const st of stackCases) {
  const ics = st.inputColumnStart || 0;
  const ctx = context(st.map, ics);
  const args = [cli, path.join(base, st.map)];
  if (ics) args.push('--input-column-start', String(ics));
  const cliOut = execFileSync('node', args, {input: st.text, encoding: 'utf8'});
  const lines = st.text.split('\n').map(line => {
    const matches = [];
    const rebuilt = line.replace(RE, (match, func, delimiter, fileName, l, c) => {
      if (delimiter === ':' && func && !fileName) {
        fileName = func;
        func = null;
      }
      const ids = ctx.parseFileName(fileName || '');
      const o = ctx.getOriginalPositionFor(l, c, ids);
      const d = ctx.getOriginalPositionDetailsFor(l, c, ids);
      matches.push([fileName || null, l == null ? null : +l, c == null ? null : +c, o.source ?? null,
        o.line ?? null, o.column ?? null, o.name ?? null, d.functionName ?? null,
        d.name ?? null, d.isIgnored]);
      return (o.source ?? 'null') + ':' + (o.line ?? 'null') + ':' + (o.name ?? 'null');
    });
    return {raw: line, rebuilt, matches};
  });
  const rebuilt = lines.map(l => l.rebuilt).join('\n');
  if (rebuilt !== cliOut) {
    throw new Error('recorded frames do not rebuild the CLI output for ' + st.id);
  }
  out.stacks.push({id: st.id, map: st.map, inputColumnStart: ics,
    lines: lines.map(({matches}) => matches)});
}
for (const p of spec.positions || []) {
  const ctx = context(p.map, 0);
  out.positions.push({id: p.id, map: p.map, points: p.points.map(([l, c]) => {
    const cliOut = execFileSync('node', [cli, path.join(base, p.map), String(l), String(c)],
      {encoding: 'utf8'}).trim();
    const o = ctx.getOriginalPositionFor(l, c, null);
    const d = ctx.getOriginalPositionDetailsFor(l, c, null);
    const expect = (o.source ?? 'null') + ':' + (o.line ?? 'null') + ':' + (o.name ?? 'null');
    if (expect !== cliOut) throw new Error('position mismatch ' + cliOut + ' vs ' + expect);
    return [l, c, o.source ?? null, o.line ?? null, o.column ?? null, o.name ?? null,
      d.functionName ?? null, d.name ?? null];
  })});
}
for (const cr of spec.crashes || []) {
  const cliOut = execFileSync('node', [cli, path.join(base, cr.map), '--hermes-crash'],
    {input: JSON.stringify({callstack: cr.callstack}), encoding: 'utf8'});
  out.crashes.push({id: cr.id, map: cr.map, callstack: cr.callstack, result: JSON.parse(cliOut)});
}
// One entry per line, so a regenerated golden diffs entry by entry.
const lines = [];
for (const key of ['stacks', 'positions', 'crashes']) {
  lines.push(JSON.stringify(key) + ': [\n' + out[key].map(e => JSON.stringify(e)).join(',\n') + '\n]');
}
fs.writeFileSync(outPath, '{\n' + lines.join(',\n') + '\n}\n');
