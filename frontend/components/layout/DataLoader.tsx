'use client'
import { useEffect } from 'react'
import { useStore } from '@/store/app'
import { getAccounts, getCategories, getSubcategories, getMonths, getTransactions } from '@/lib/api'

export default function DataLoader() {
  const {
    setAccounts, setCategories, setSubcategories, setMonths, setPendingCount,
    addToast, refreshKey, catalogRefreshKey, monthsRefreshKey,
  } = useStore()

  useEffect(() => {
    Promise.all([
      getAccounts().then(setAccounts),
      getCategories().then(setCategories),
      getSubcategories().then(setSubcategories),
    ]).catch(() => addToast('Cadastros auxiliares nao puderam ser carregados', 'err'))
  }, [catalogRefreshKey])

  useEffect(() => {
    getMonths()
      .then(setMonths)
      .catch(() => addToast('Meses disponiveis nao puderam ser carregados', 'err'))
  }, [monthsRefreshKey])

  useEffect(() => {
    getTransactions({ status: 'pending', reconciliation_status: 'unmatched', page_size: 1 })
      .then(data => setPendingCount(data.total))
      .catch(() => addToast('Total de pendentes nao pode ser atualizado', 'err'))
  }, [refreshKey])

  return null
}
