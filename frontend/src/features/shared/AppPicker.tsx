import { useState } from 'react'
import type { DevicePackage } from '@/api/types'
import { ChoiceList, SearchInput, Stack } from '@/design'
import { searchApps } from '@/domain/installed'

/** The installed apps to profile or trace, searchable by the name the phone
 *  shows or the package id. Capture and Manual share it. */
export function AppPicker({
  apps,
  value,
  onChange,
  label,
  describe = (p) => p.pkg,
  maxHeight = 360,
}: {
  apps: DevicePackage[]
  value: string | null
  onChange: (pkg: string) => void
  label: string
  /** The second line under an app's name; its package id by default. */
  describe?: (p: DevicePackage) => string
  maxHeight?: number
}) {
  const [q, setQ] = useState('')
  return (
    <Stack gap={12}>
      <SearchInput label="Search installed apps" placeholder="Search by name or package id" value={q} onChange={setQ} />
      <ChoiceList
        label={label}
        maxHeight={maxHeight}
        value={value}
        onChange={onChange}
        options={searchApps(apps, q).map((p) => ({ value: p.pkg, title: `${p.name}${p.role === 'own' ? ' · ours' : ''}`, description: describe(p) }))}
        empty="No installed apps match that search."
      />
    </Stack>
  )
}
