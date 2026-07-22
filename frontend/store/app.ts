'use client'

import { create } from 'zustand'
import type { Account, Category, Subcategory } from '@/types'

type ToastType = 'ok' | 'err'

export interface AppToast {
  id: string
  msg: string
  type: ToastType
}

interface AppState {
  accounts: Account[]
  categories: Category[]
  subcategories: Subcategory[]
  months: string[]
  pendingCount: number
  toasts: AppToast[]
  refreshKey: number
  catalogRefreshKey: number
  monthsRefreshKey: number
  setAccounts: (accounts: Account[]) => void
  setCategories: (categories: Category[]) => void
  setSubcategories: (subcategories: Subcategory[]) => void
  setMonths: (months: string[]) => void
  setPendingCount: (pendingCount: number) => void
  addToast: (msg: string, type?: ToastType) => void
  removeToast: (id: string) => void
  bumpRefresh: () => void
  bumpCatalogRefresh: () => void
  bumpMonthsRefresh: () => void
}

export const useStore = create<AppState>((set) => ({
  accounts: [],
  categories: [],
  subcategories: [],
  months: [],
  pendingCount: 0,
  toasts: [],
  refreshKey: 0,
  catalogRefreshKey: 0,
  monthsRefreshKey: 0,
  setAccounts: (accounts) => set({ accounts }),
  setCategories: (categories) => set({ categories }),
  setSubcategories: (subcategories) => set({ subcategories }),
  setMonths: (months) => set({ months }),
  setPendingCount: (pendingCount) => set({ pendingCount }),
  addToast: (msg, type = 'ok') => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`
    set((state) => ({ toasts: [...state.toasts, { id, msg, type }] }))
    window.setTimeout(() => {
      set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) }))
    }, 3500)
  },
  removeToast: (id) => set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) })),
  bumpRefresh: () => set((state) => ({ refreshKey: state.refreshKey + 1 })),
  bumpCatalogRefresh: () => set((state) => ({ catalogRefreshKey: state.catalogRefreshKey + 1 })),
  bumpMonthsRefresh: () => set((state) => ({ monthsRefreshKey: state.monthsRefreshKey + 1 })),
}))
