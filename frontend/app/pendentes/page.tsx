import TransactionTable from '@/components/transactions/TransactionTable'
export default function Page() {
  return (
    <TransactionTable
      defaultStatus="pending"
      defaultSortBy="match_probability"
      defaultSortOrder="desc"
    />
  )
}
