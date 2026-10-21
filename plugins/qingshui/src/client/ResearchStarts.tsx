/** Everyday questions that start a blank research chat. */
export const RESEARCH_STARTS = [
  '这只票的毛利率，是不是又上台阶了',
  '芯片板块今天为什么这么热',
  '今天大盘涨跌家数和成交额怎么样',
  '复盘上个交易日',
] as const

/** Suggested questions under the centered composer. Clicking one sends it. */
export function ResearchStarts(props: { onAsk: (text: string) => void }): React.ReactElement {
  return (
    <div className="qs-starts">
      {RESEARCH_STARTS.map(text => (
        <button key={text} type="button" className="qs-starts-row" onClick={() => { props.onAsk(text) }}>
          {text}
        </button>
      ))}
    </div>
  )
}
