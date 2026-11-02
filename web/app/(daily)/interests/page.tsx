import { Interests } from "@/components/daily/Interests";
import seed from "@/lib/daily/topics.json";
export default function InterestsPage() {
  return <Interests topics={seed.topics} />;
}
