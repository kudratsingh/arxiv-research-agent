/** One polite result announcement per daily route; TraceSpine belongs to other shells. */
export function Announcement({ children }: { children: React.ReactNode }) {
  return <p role="status">{children}</p>;
}
