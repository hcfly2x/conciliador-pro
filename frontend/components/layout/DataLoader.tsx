'use client'
import { useEffect } from 'react'
import { useStore } from '@/store/app'
import { getAccounts, getCategories, getSubcategories, getMonths, getTransactions } from '@/lib/api'

export default function DataLoader() {
  const { setAccounts, setCategories, setSubcategories, setMonths, setPendingCount, refreshKey } = useStore()

  useEffect(() => {
    getAccounts().then(setAccounts).catch(() => {})
    getCategories().then(setCategories).catch(() => {})
    getSubcategories().then(setSubcategories).catch(() => {})
    getMonths().then(setMonths).catch(() => {})
    getTransactions({ status: 'pending', page_size: 1 }).then(data => setPendingCount(data.total)).catch(() => {})
  }, [refreshKey])

  return null
}
