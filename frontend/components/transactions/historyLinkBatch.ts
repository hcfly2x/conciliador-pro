import { prepareHistoricalLinks, type HistoryLinkBatchResult } from '@/lib/api'

export interface HistoryLinkBatchLog {
  time: string
  message: string
}

export interface HistoryLinkBatchProgress {
  total: number
  completed: number
  currentBlock: number
  blockCount: number
  matched: number
  manualReview: number
  withoutMatch: number
  skipped: number
  failed: number
  status: 'running' | 'completed' | 'error'
}

const CHUNK_SIZE = 10

function unique(values: string[]): string[] {
  return [...new Set(values)]
}

function emptyResult(selected: number): HistoryLinkBatchResult {
  return {
    selected,
    matched: 0,
    manual_review: 0,
    without_match: 0,
    skipped: 0,
    failed: 0,
    matched_ids: [],
    manual_review_ids: [],
    without_match_ids: [],
    skipped_ids: [],
    failed_ids: [],
    affected_ids: [],
    operation_id: '',
    duration_ms: 0,
    logs: [],
  }
}

function mergeResult(target: HistoryLinkBatchResult, part: HistoryLinkBatchResult): void {
  target.matched += part.matched
  target.manual_review += part.manual_review
  target.without_match += part.without_match
  target.skipped += part.skipped
  target.failed += part.failed
  target.duration_ms += part.duration_ms
  target.matched_ids = unique([...target.matched_ids, ...part.matched_ids])
  target.manual_review_ids = unique([...target.manual_review_ids, ...part.manual_review_ids])
  target.without_match_ids = unique([...target.without_match_ids, ...part.without_match_ids])
  target.skipped_ids = unique([...target.skipped_ids, ...part.skipped_ids])
  target.failed_ids = unique([...target.failed_ids, ...part.failed_ids])
  target.affected_ids = unique([...target.affected_ids, ...part.affected_ids])
}

export async function runHistoricalLinkBatch(
  ids: string[],
  onLog: (entry: HistoryLinkBatchLog) => void,
  onProgress: (progress: HistoryLinkBatchProgress) => void,
): Promise<HistoryLinkBatchResult> {
  const result = emptyResult(ids.length)
  const chunkCount = Math.ceil(ids.length / CHUNK_SIZE)
  const localTime = () => new Date().toLocaleTimeString('pt-BR', { hour12: false })
  const operationIds: string[] = []

  const reportProgress = (
    completed: number,
    currentBlock: number,
    status: HistoryLinkBatchProgress['status'] = 'running',
  ) => onProgress({
    total: ids.length,
    completed,
    currentBlock,
    blockCount: chunkCount,
    matched: result.matched,
    manualReview: result.manual_review,
    withoutMatch: result.without_match,
    skipped: result.skipped,
    failed: result.failed,
    status,
  })

  reportProgress(0, 1)
  onLog({
    time: localTime(),
    message: `${ids.length} lancamento(s) divididos em ${chunkCount} bloco(s) de ate ${CHUNK_SIZE}`,
  })

  for (let index = 0; index < chunkCount; index += 1) {
    const chunk = ids.slice(index * CHUNK_SIZE, (index + 1) * CHUNK_SIZE)
    const completedBefore = index * CHUNK_SIZE
    onLog({
      time: localTime(),
      message: `Bloco ${index + 1}/${chunkCount} enviado: itens ${completedBefore + 1}-${completedBefore + chunk.length}; ${completedBefore}/${ids.length} concluidos`,
    })
    reportProgress(completedBefore, index + 1)

    let part: HistoryLinkBatchResult
    try {
      part = await prepareHistoricalLinks(chunk)
    } catch (error) {
      const detail = (error as { detail?: string })?.detail || 'erro de comunicacao com o servidor'
      onLog({
        time: localTime(),
        message: `Bloco ${index + 1}/${chunkCount} sem resposta: ${detail}. ${completedBefore}/${ids.length} estavam concluidos antes deste bloco`,
      })
      reportProgress(completedBefore, index + 1, 'error')
      throw error
    }

    mergeResult(result, part)
    if (part.operation_id) operationIds.push(part.operation_id)
    for (const entry of part.logs || []) {
      onLog({ time: localTime(), message: `[bloco ${index + 1}/${chunkCount}] ${entry.message}` })
    }
    const completed = Math.min((index + 1) * CHUNK_SIZE, ids.length)
    reportProgress(completed, index + 1)
    onLog({
      time: localTime(),
      message: `Progresso real: ${completed}/${ids.length} analisados; ${result.matched} confirmados; ${result.manual_review} para revisao; ${result.without_match} sem vinculo; ${result.failed} falhas`,
    })
  }

  result.operation_id = operationIds.join(',')
  onLog({
    time: localTime(),
    message: `Lote completo: ${ids.length}/${ids.length} analisados em ${chunkCount} bloco(s)`,
  })
  reportProgress(ids.length, chunkCount, 'completed')
  return result
}
