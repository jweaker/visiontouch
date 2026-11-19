// Quiz: multiple choice with four giant answer tiles. Questions live in src/quiz.json.
import questions from '../quiz.json'
import { C, burst, dialog, shuffle, type App } from '../ui'

const TILE_COLORS = [C.cobalt, C.tomato, C.mint, C.pink]

export const quiz: App = {
  id: 'quiz',
  title: 'Quiz',
  blurb: 'Test your DIP basics.',
  color: C.pink,
  icon: '<svg viewBox="0 0 64 64"><path d="M22 22a10 10 0 1 1 14 9c-3 2-4 4-4 8"/><circle cx="32" cy="52" r="3"/></svg>',

  mount(root) {
    root.innerHTML = `
      <div class="quiz">
        <div class="quiz-head">
          <span class="pill quiz-progress"></span>
          <h2 class="quiz-q"></h2>
          <p class="quiz-why"></p>
          <button class="btn big quiz-next" style="--c:${C.cobalt}" hidden>Next →</button>
        </div>
        <div class="quiz-answers">
          ${TILE_COLORS.map((c, i) => `<button class="answer tap" style="--c:${c}"><b>${'ABCD'[i]}</b><span></span></button>`).join('')}
        </div>
      </div>`
    const $ = <T extends Element>(s: string) => root.querySelector<T>(s)!
    const tiles = [...root.querySelectorAll<HTMLButtonElement>('.answer')]
    let order: typeof questions = [], n = 0, score = 0, answered = false

    function start() {
      order = shuffle([...questions]).slice(0, 10)
      n = score = 0
      ask()
    }
    function ask() {
      const q = order[n]
      answered = false
      $('.quiz-progress').textContent = `Question ${n + 1} of ${order.length} · Score ${score}`
      $('.quiz-q').textContent = q.q
      $('.quiz-why').textContent = ''
      $<HTMLElement>('.quiz-next').hidden = true
      tiles.forEach((t, i) => {
        t.className = 'answer tap'
        t.querySelector('b')!.textContent = 'ABCD'[i]
        t.querySelector('span')!.textContent = q.choices[i]
      })
    }
    tiles.forEach((t, i) =>
      t.addEventListener('click', (e) => {
        if (answered) return
        answered = true
        const q = order[n]
        const right = i === q.answer
        if (right) {
          score++
          burst(e.clientX, e.clientY, C.sun, 20)
        }
        tiles.forEach((x, j) => {
          x.classList.add(j === q.answer ? 'right' : j === i ? 'wrong' : 'dim')
          if (j === q.answer) x.querySelector('b')!.textContent = '✓'
          else if (j === i) x.querySelector('b')!.textContent = '✗'
        })
        $('.quiz-why').textContent = `${right ? 'Correct!' : 'Not quite.'} ${q.why}`
        $('.quiz-progress').textContent = `Question ${n + 1} of ${order.length} · Score ${score}`
        $<HTMLElement>('.quiz-next').hidden = false
      }),
    )
    $('.quiz-next').addEventListener('click', () => {
      if (++n < order.length) return ask()
      dialog(root, {
        title: `${score} / ${order.length}`,
        body: score >= 8 ? 'Excellent — you know your pixels.' : score >= 5 ? 'Good work!' : 'Keep practising!',
        actions: [{ label: 'Play again', onTap: start }],
      })
    })
    start()
    return () => {}
  },
}
