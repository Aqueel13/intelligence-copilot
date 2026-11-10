import { useQuery } from '@tanstack/react-query'
import { createContext, useContext, useState, type ReactNode } from 'react'
import { actionsApi, type DemoUser } from '../api/investigation'

const KEY = 'watchdog.actingUser'
const Ctx = createContext<{ user: DemoUser | null; users: DemoUser[]; setUserId: (id: string) => void }>({
  user: null,
  users: [],
  setUserId: () => {},
})

function stored(): string | null {
  try {
    return localStorage.getItem(KEY)
  } catch {
    return null
  }
}

/** Demo identity until login exists (M8). Remembered per browser only. */
export function ActingUserProvider({ children }: { children: ReactNode }) {
  const users = useQuery({ queryKey: ['demo-users'], queryFn: actionsApi.users, staleTime: Infinity })
  const [id, setId] = useState<string | null>(stored)
  const list = users.data ?? []
  const user = list.find((u) => u.id === id) ?? list.find((u) => u.role === 'Operations Analyst') ?? list[0] ?? null
  const setUserId = (next: string) => {
    setId(next)
    try {
      localStorage.setItem(KEY, next)
    } catch {
      /* storage unavailable: keep in memory */
    }
  }
  return <Ctx.Provider value={{ user, users: list, setUserId }}>{children}</Ctx.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export const useActingUser = () => useContext(Ctx)
