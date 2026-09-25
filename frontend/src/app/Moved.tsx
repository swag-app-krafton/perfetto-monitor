import { Navigate, useLocation } from 'react-router'

/** A moved screen's old address, keeping the run and focus in the query. */
export function Moved({ to }: { to: string }) {
  const { search, hash } = useLocation()
  return <Navigate to={`${to}${search}${hash}`} replace />
}
