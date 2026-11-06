import type { BoundSource, SourceReference } from "@/lib/workspace/api";

const scopeLabels = {
  metadata: "Source metadata",
  abstract: "Abstract",
  excerpt: "Retained excerpt",
  full_text: "Full text",
};

/** Keep exact source bindings inspectable without making identifiers the headline. */
export function SourceReferenceDetails({ reference }: { reference: SourceReference }) {
  const source = reference as SourceReference & Partial<BoundSource>;
  const versionNumber = /:v(\d+)(?::metadata-[a-f0-9]+)?$/.exec(source.version_id)?.[1];
  const scope = source.source_scope ?? (/^(metadata|abstract|excerpt|full_text):/.exec(source.anchor)?.[1] as keyof typeof scopeLabels | undefined);
  return <>
    <p className="ws-context-status">{versionNumber ? `Version ${versionNumber}` : "Pinned source version"} · {scope ? scopeLabels[scope] : "Retained source context"}{source.page != null ? ` · Page ${source.page}` : ""}</p>
    <details className="ws-record-details">
      <summary>Exact source details</summary>
      <dl>
        <dt>Source ID</dt><dd>{source.work_id}</dd>
        <dt>Version ID</dt><dd>{source.version_id}</dd>
        <dt>Anchor</dt><dd>{source.anchor}</dd>
        {source.version_hash != null && <><dt>Version hash</dt><dd>{source.version_hash}</dd></>}
        {source.source_scope != null && <><dt>Source scope</dt><dd>{source.source_scope}</dd></>}
        {source.material_id != null && <><dt>Material ID</dt><dd>{source.material_id}</dd></>}
        {source.material_hash != null && <><dt>Material hash</dt><dd>{source.material_hash}</dd></>}
        {source.parser_revision != null && <><dt>Parser revision</dt><dd>{source.parser_revision}</dd></>}
        {source.source_url && <><dt>Source URL</dt><dd>{source.source_url}</dd></>}
        {source.page != null && <><dt>Page</dt><dd>{source.page}</dd></>}
        {source.start != null && <><dt>Start offset</dt><dd>{source.start}</dd></>}
        {source.end != null && <><dt>End offset</dt><dd>{source.end}</dd></>}
        {source.offset_basis && <><dt>Offset basis</dt><dd>{source.offset_basis}</dd></>}
      </dl>
    </details>
  </>;
}
