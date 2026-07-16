function parseTask(payload) {
  const data = JSON.parse(payload)

  if (typeof data.topic !== 'string' || data.topic.trim() === '') {
    throw new TypeError('topic must be a non-empty string')
  }

  const maxSources = data.maxSources ?? 3
  if (!Number.isInteger(maxSources)) {
    throw new TypeError('maxSources must be an integer')
  }

  return Object.freeze({ topic: data.topic, maxSources })
}

async function execute(task) {
  await Promise.resolve()
  return { status: 'completed', task }
}

const task = parseTask('{"topic":"MCP Server","maxSources":2}')
console.log(JSON.stringify(await execute(task)))
