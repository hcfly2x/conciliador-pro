'use client'
import { useEffect } from 'react'
import { useStore } from '@/store/app'
import { getAccounts, getCategories, getSubcategories, getMonths, getTransactions } from '@/lib/api'

export default function DataLoader() {
  const { setAccounts, setCategories, setSubcategories, setMonths, setPendingCount, addToast, refreshKey } = useStore()

  useEffect(() => {
    Promise.all([
      getAccounts().then(setAccounts),
      getCategories().then(setCategories),
      getSubcategories().then(setSubcategories),
      getMonths().then(setMonths),
      getTransactions({ status: 'pending', page_size: 1 }).then(data => setPendingCount(data.total)),
    ]).catch(() => addToast('Alguns dados iniciais nao puderam ser carregados', 'err'))
  }, [refreshKey])

  return null
}
