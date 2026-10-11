// Run a workspace task by label: command `runTask.byName` (arg = label, else asks) or
// URI <scheme>://awto.run-task/run?name=<label>. Only tasks the open workspace defines.
const vscode = require('vscode');

async function run(name) {
  if (!name) {
    return;
  }
  if (vscode.tasks.taskExecutions.some((e) => e.task.name === name)) {
    return; // already running
  }
  const task = (await vscode.tasks.fetchTasks()).find((t) => t.name === name);
  if (!task) {
    vscode.window.showWarningMessage(`Run task: no task named "${name}" in this workspace`);
    return;
  }
  await vscode.tasks.executeTask(task);
}

function activate(context) {
  context.subscriptions.push(
    vscode.commands.registerCommand('runTask.byName', async (name) =>
      run(name || (await vscode.window.showInputBox({ prompt: 'Task label' })))),
    vscode.window.registerUriHandler({
      handleUri(uri) {
        if (uri.path === '/run') {
          return run(new URLSearchParams(uri.query).get('name'));
        }
      },
    }),
  );
}

module.exports = { activate, deactivate() {} };
