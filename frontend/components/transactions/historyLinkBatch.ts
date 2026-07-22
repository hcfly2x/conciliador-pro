import { prepareHistoricalLinks, type HistoryLinkBatchResult } from '@/lib/api'

export interface HistoryLinkBatchLog {
  time: string
  message: string
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
): Promise<HistoryLinkBatchResult> {
  const result = emptyResult(ids.length)
  const chunkCount = Math.ceil(ids.length / CHUNK_SIZE)
  const localTime = () => new Date().toLocaleTimeString('pt-BR', { hour12: false })
  const operationIds: string[] = []

  onLog({
    time: localTime(),
    message: `${ids.length} lancamento(s) divididos em ${chunkCount} bloco(s) de ate ${CHUNK_SIZE}`,
  })

  for (let index = 0; index < chunkCount; index += 1) {
    const chunk = ids.slice(index * CHUNK_SIZE, (index + 1) * CHUNK_SIZE)
    const completedBefore = index * CHUNK_SIZE
    const blockStartedAt = Date.now()
    onLog({
      time: localTime(),
      message: `Bloco ${index + 1}/${chunkCount} enviado: itens ${completedBefore + 1}-${completedBefore + chunk.length}; ${completedBefore}/${ids.length} concluidos`,
    })
    const heartbeat = window.setInterval(() => {
      const elapsed = Math.round((Date.now() - blockStartedAt) / 1000)
      onLog({
        time: localTime(),
        message: `Bloco ${index + 1}/${chunkCount} em processamento ha ${elapsed}s; ${completedBefore}/${ids.length} concluidos`,
      })
    }, 5000)

    let part: HistoryLinkBatchResult
    try {
      part = await prepareHistoricalLinks(chunk)
    } catch (error) {
      const detail = (error as { detail?: string })?.detail || 'erro de comunicacao com o servidor'
      onLog({
        time: localTime(),
        message: `Bloco ${index + 1}/${chunkCount} sem resposta: ${detail}. ${completedBefore}/${ids.length} estavam concluidos antes deste bloco`,
      })
      throw error
    } finally {
      window.clearInterval(heartbeat)
    }

    mergeResult(result, part)
    if (part.operation_id) operationIds.push(part.operation_id)
    for (const entry of part.logs || []) {
      onLog({ time: entry.time, message: `[bloco ${index + 1}/${chunkCount}] ${entry.message}` })
    }
    const completed = Math.min((index + 1) * CHUNK_SIZE, ids.length)
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
  return result
}
