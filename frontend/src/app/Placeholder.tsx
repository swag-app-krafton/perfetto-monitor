import { EmptyState } from '@/design/components'

/** Temporary content for screens not yet rebuilt. */
export function Placeholder({ id }: { id: string }) {
  return <EmptyState title="Coming next">The {id} screen is being rebuilt.</EmptyState>
}
