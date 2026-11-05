import { Suspense } from "react";
import { LiveProjects } from "@/components/workspace/Projects";
export default function Page() { return <Suspense fallback={<p aria-busy="true">Opening projects…</p>}><LiveProjects /></Suspense>; }
