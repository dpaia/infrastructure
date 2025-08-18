const { Probot } = require("probot");
require('dotenv').config();
const path = require('path');
const { spawn } = require('child_process');
const fs = require('fs');

// DRY_RUN mode prevents actual dispatches and logs intent for local testing
const DRY_RUN = /^true$/i.test(process.env.DRY_RUN || 'false');

// Helpers for local execution
const repoRoot = path.resolve(__dirname, '..');

function run(cmd, args = [], options = {}) {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, {
      cwd: options.cwd || repoRoot,
      env: options.env || process.env,
      shell: options.shell || false
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (d) => { stdout += d.toString(); });
    child.stderr.on('data', (d) => { stderr += d.toString(); });
    child.on('close', (code) => resolve({ code, stdout, stderr }));
  });
}

function getPythonBin() {
  return process.env.PYTHON_BIN || 'python3';
}

async function ensurePythonModule(moduleName) {
  const py = getPythonBin();
  let check = await run(py, ['-c', `import ${moduleName}`]);
  if (check.code === 0) return true;
  // Try to install
  await run(py, ['-m', 'pip', 'install', '--user', moduleName]);
  check = await run(py, ['-c', `import ${moduleName}`]);
  return check.code === 0;
}

function parseTarget(target) {
  const m = /^([^\/]+)\/([^\/]+)\/issues\/(\d+)$/.exec(String(target || ''));
  if (!m) return null;
  return { organization: m[1], repository: m[2], issueNumber: m[3] };
}

async function ghLines(args) {
  const res = await run('gh', ['api', ...args]);
  if (res.code !== 0) throw new Error(`gh api failed: ${res.stderr || res.stdout}`);
  const out = res.stdout.trim();
  return out ? out.split('\n').filter(Boolean) : [];
}

async function ghGetCommitDate(org, repo, sha) {
  const res = await run('gh', ['api', `repos/${org}/${repo}/commits/${sha}`, '--jq', '.commit.author.date']);
  if (res.code !== 0) throw new Error(`Failed to get commit date for ${sha}: ${res.stderr}`);
  return res.stdout.trim();
}

async function getLinkedCommits(org, repo, issue) {
  // Directly referenced commits on the issue timeline
  let commits = [];
  try {
    const lines = await ghLines([`repos/${org}/${repo}/issues/${issue}/timeline`, '--jq', '.[] | select(.event == "referenced" and .commit_id != null) | .commit_id']);
    commits.push(...lines);
  } catch (e) {
    // ignore, will try PRs
  }
  // If none, check cross-referenced PRs
  if (commits.length === 0) {
    try {
      const prs = await ghLines([`repos/${org}/${repo}/issues/${issue}/timeline`, '--jq', '.[] | select(.event == "cross-referenced" and .source.issue.pull_request != null) | .source.issue.number']);
      for (const pr of prs) {
        const prCommits = await ghLines([`repos/${org}/${repo}/pulls/${pr}/commits`, '--jq', '.[].sha']);
        commits.push(...prCommits);
      }
    } catch (e) {
      // ignore
    }
  }
  // Unique
  commits = Array.from(new Set(commits));
  if (commits.length === 0) return { commits: [], latest: '', base: '' };
  // Sort by commit date
  const withDates = [];
  for (const sha of commits) {
    try {
      const date = await ghGetCommitDate(org, repo, sha);
      withDates.push({ sha, date: new Date(date).getTime() });
    } catch (e) {
      // skip if date fetch fails
    }
  }
  if (withDates.length === 0) return { commits: [], latest: '', base: '' };
  withDates.sort((a, b) => a.date - b.date);
  return {
    commits: withDates.map(c => c.sha),
    base: withDates[0].sha,
    latest: withDates[withDates.length - 1].sha
  };
}

async function extractTestFields(org, repo, issue, envExtra = {}) {
  const py = getPythonBin();
  const script = path.join(repoRoot, '.github/python/utils/extract_test_fields.py');
  const env = { ...process.env, ...envExtra, ISSUE_NUMBER: String(issue), REPOSITORY: repo, ORGANIZATION: org };
  const res = await run(py, [script], { env });
  if (res.code !== 0) throw new Error(`extract_test_fields.py failed: ${res.stderr}`);
  const lines = res.stdout.split('\n');
  const out = { fail_to_pass: '[]', pass_to_pass: '[]', metadata: '', comment_id: '', has_error: 'true' };
  for (const line of lines) {
    const m = /^(fail_to_pass|pass_to_pass|metadata|comment_id|has_error)=(.*)$/.exec(line.trim());
    if (m) {
      out[m[1]] = m[2];
    }
  }
  return out;
}

async function generateData(params) {
  const { org, repo, issue, latest, base, commits, failToPass, passToPass, metadata } = params;
  const py = getPythonBin();
  await ensurePythonModule('unidiff');
  const script = path.join(repoRoot, '.github/python/java.py');
  const env = {
    ...process.env,
    ISSUE_NUMBER: String(issue),
    REPOSITORY: repo,
    ORGANIZATION: org,
    LATEST_COMMIT: latest || '',
    BASE_COMMIT: base || '',
    LINKED_COMMITS: JSON.stringify(commits || []),
    GH_TOKEN: process.env.GH_TOKEN || '',
    FAIL_TO_PASS: failToPass || '[]',
    PASS_TO_PASS: passToPass || '[]',
    METADATA: metadata || ''
  };
  const res = await run(py, [script], { env });
  if (res.code !== 0) {
    // Try to parse stdout anyway (script prints JSON even on error)
    try { return JSON.parse((res.stdout || '').trim()); } catch (e) {}
    throw new Error(`java.py failed: ${res.stderr}`);
  }
  const text = (res.stdout || '').trim();
  return JSON.parse(text);
}

async function verifyInstance(data, latest, base) {
  const script = path.join(repoRoot, '.github/scripts/verify_java_dataset_instance.sh');
  const preferBase = base && base !== 'null' ? base : latest;
  const commit = (data.base_commit && data.base_commit !== 'null') ? data.base_commit : preferBase;
  let isMaven = data.is_maven;
  if (typeof isMaven !== 'string') isMaven = String(isMaven);
  isMaven = isMaven.toLowerCase();
  const args = [
    data.repo || `${data.organization}/${data.repository}.git`,
    commit || '',
    data.patch || '',
    data.test_patch || '',
    data.FAIL_TO_PASS || '[]',
    data.PASS_TO_PASS || '[]',
    '',
    isMaven,
    '24',
    data.instance_id || ''
  ];
  // Run via bash to avoid +x requirement
  const res = await run('bash', [script, ...args], { env: process.env });
  return { code: res.code, logs: res.stdout + (res.stderr ? `\n[stderr]\n${res.stderr}` : '') };
}

function extractIssueNumbers(text) {
  if (!text) return [];
  const results = new Set();
  const patterns = [
    /(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)/gi, // closes #123
    /#(\d+)/g // any #123
  ];
  for (const re of patterns) {
    let m;
    while ((m = re.exec(text)) !== null) {
      const num = parseInt(m[1], 10);
      if (!isNaN(num)) results.add(num);
    }
  }
  return Array.from(results);
}

async function dispatchWorkflow(octokit, params) {
  const {
    infraOwner,
    infraRepo,
    workflowFile,
    ref,
    organization,
    repository,
    issueNumber,
    datasetRepo,
    generator,
    autoMerge
  } = params;

  if (DRY_RUN) {
    console.log(`[DRY_RUN] Would dispatch workflow`, {
      owner: infraOwner,
      repo: infraRepo,
      workflow_id: workflowFile,
      ref,
      inputs: {
        organization,
        repository,
        issue_id: String(issueNumber),
        dataset_repo: datasetRepo,
        generator: generator || 'java',
        auto_merge: String(Boolean(autoMerge))
      }
    });
    return;
  }

  await octokit.request('POST /repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches', {
    owner: infraOwner,
    repo: infraRepo,
    workflow_id: workflowFile,
    ref: ref,
    inputs: {
      organization,
      repository,
      issue_id: String(issueNumber),
      dataset_repo: datasetRepo,
      generator: generator || 'java',
      auto_merge: String(Boolean(autoMerge))
    }
  });
}

module.exports = (app) => {
  const INFRA_REPO_FULL = process.env.INFRA_REPO; // e.g. my-org/infrastructure
  const INFRA_REF = process.env.INFRA_REF || 'main';
  const WORKFLOW_FILE = process.env.WORKFLOW_FILE || '.github/workflows/process-issue.yml';
  const DATASET_REPO = process.env.DATASET_REPO || '';
  const GENERATOR = process.env.GENERATOR || 'java';
  const AUTO_MERGE = /^true$/i.test(process.env.AUTO_MERGE || 'false');

  // Expose a basic health endpoint for local testing
  try {
    if (app.router) {
      app.router.get('/health', (_req, res) => {
        res.status(200).json({ status: 'ok', dry_run: DRY_RUN });
      });
      
      // Local validation endpoint
      // Usage: GET /validate?target=org/repo/issues/123
      app.router.get('/validate', async (req, res) => {
        const target = req.query.target || req.query.issue || req.query.t;
        const parsed = parseTarget(target);
        if (!parsed) {
          return res.status(400).json({ ok: false, error: 'Invalid target format. Expected org/repo/issues/NUMBER', example: 'jetbrains-eval-lab/spring-petclinic/issues/79' });
        }
        const { organization, repository, issueNumber } = parsed;

        try {
          const commitsInfo = await getLinkedCommits(organization, repository, issueNumber);
          if (!commitsInfo.latest) {
            return res.status(400).json({ ok: false, input: parsed, error: 'No linked commits found for the issue' });
          }

          const testFields = await extractTestFields(organization, repository, issueNumber);
          const missingTests = (testFields.fail_to_pass === '[]') && (testFields.pass_to_pass === '[]');

          const dataValue = await generateData({
            org: organization,
            repo: repository,
            issue: issueNumber,
            latest: commitsInfo.latest,
            base: commitsInfo.base,
            commits: commitsInfo.commits,
            failToPass: testFields.fail_to_pass,
            passToPass: testFields.pass_to_pass,
            metadata: testFields.metadata
          });

          let verification = null;
          if (!missingTests) {
            verification = await verifyInstance(dataValue, commitsInfo.latest, commitsInfo.base);
          }

          return res.status(200).json({
            ok: missingTests ? true : (verification ? verification.code === 0 : true),
            input: parsed,
            commits: commitsInfo,
            test_fields: testFields,
            missing_tests: missingTests,
            data_value: dataValue,
            verification: verification ? { exit_code: verification.code, status: verification.code === 0 ? 'Success' : 'Failure', logs: verification.logs } : null
          });
        } catch (e) {
          return res.status(500).json({ ok: false, input: parsed, error: (e && e.message) ? e.message : String(e) });
        }
      });

      app.log.info('Health endpoint mounted at GET /health');
      app.log.info('Validation endpoint mounted at GET /validate?target=org/repo/issues/123');
    }
  } catch (e) {
    app.log.warn('Could not register health/validate endpoints', e);
  }

  if (!INFRA_REPO_FULL) {
    app.log.warn('INFRA_REPO is not set. The app will not dispatch workflows.');
  }

  function getInfra() {
    if (!INFRA_REPO_FULL || !INFRA_REPO_FULL.includes('/')) return null;
    const [owner, repo] = INFRA_REPO_FULL.split('/');
    return { owner, repo };
  }

  // Push events: parse commit messages for referenced issues
  app.on('push', async (context) => {
    const infra = getInfra();
    if (!infra) return;
    const org = context.payload.repository.owner.login;
    const repo = context.payload.repository.name;

    const commitMessages = (context.payload.commits || []).map(c => c.message || '').join('\n\n');
    const issues = extractIssueNumbers(commitMessages);
    if (issues.length === 0) return;

    const octokit = context.octokit;
    for (const issue of issues) {
      await dispatchWorkflow(octokit, {
        infraOwner: infra.owner,
        infraRepo: infra.repo,
        workflowFile: WORKFLOW_FILE,
        ref: INFRA_REF,
        organization: org,
        repository: repo,
        issueNumber: issue,
        datasetRepo: DATASET_REPO,
        generator: GENERATOR,
        autoMerge: AUTO_MERGE
      });
      app.log.info(`Dispatched workflow for ${org}/${repo} issue #${issue} (push)`);
    }
  });

  // Pull request events: parse PR title and body for referenced issues
  app.on(["pull_request.opened", "pull_request.synchronize", "pull_request.ready_for_review"], async (context) => {
    const infra = getInfra();
    if (!infra) return;
    const org = context.payload.repository.owner.login;
    const repo = context.payload.repository.name;
    const pr = context.payload.pull_request;

    const text = `${pr.title || ''}\n\n${pr.body || ''}`;
    const issues = extractIssueNumbers(text);
    if (issues.length === 0) return;

    const octokit = context.octokit;
    for (const issue of issues) {
      await dispatchWorkflow(octokit, {
        infraOwner: infra.owner,
        infraRepo: infra.repo,
        workflowFile: WORKFLOW_FILE,
        ref: INFRA_REF,
        organization: org,
        repository: repo,
        issueNumber: issue,
        datasetRepo: DATASET_REPO,
        generator: GENERATOR,
        autoMerge: AUTO_MERGE
      });
      app.log.info(`Dispatched workflow for ${org}/${repo} issue #${issue} (pr)`);
    }
  });

  // Issue comments: if includes FAIL_TO_PASS or PASS_TO_PASS, trigger for the issue itself
  app.on(["issue_comment.created", "issue_comment.edited"], async (context) => {
    const infra = getInfra();
    if (!infra) return;
    const body = context.payload.comment && context.payload.comment.body || '';
    if (!/FAIL_TO_PASS:|PASS_TO_PASS:/i.test(body)) return;

    const org = context.payload.repository.owner.login;
    const repo = context.payload.repository.name;
    const issueNumber = context.payload.issue && context.payload.issue.number;
    if (!issueNumber) return;

    const octokit = context.octokit;
    await dispatchWorkflow(octokit, {
      infraOwner: infra.owner,
      infraRepo: infra.repo,
      workflowFile: WORKFLOW_FILE,
      ref: INFRA_REF,
      organization: org,
      repository: repo,
      issueNumber: issueNumber,
      datasetRepo: DATASET_REPO,
      generator: GENERATOR,
      autoMerge: AUTO_MERGE
    });
    app.log.info(`Dispatched workflow for ${org}/${repo} issue #${issueNumber} (issue_comment)`);
  });
};
