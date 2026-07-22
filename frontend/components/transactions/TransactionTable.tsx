'use client'
import { useTransactionTable, type Props } from './useTransactionTable'
import { TransactionControls } from './TransactionControls'
import { TransactionGrid } from './TransactionGrid'
import { TransactionHistoryModal } from './TransactionHistoryModal'

export default function TransactionTable(props: Props) {
  const model = useTransactionTable(props)
  return (
    <div>
      <TransactionControls model={model} />
      <TransactionGrid model={model} />
      <TransactionHistoryModal model={model} />
    </div>
  )
}
