import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { runtimeConfig } from "./context.ts";
import { activeWorkspace, projectRoot, readJsonFile } from "./paths.ts";
import { PAPER_ID_RE, createPaper, readPaper, usePaper, writePaper } from "./paper-store.ts";

const PROJECT_KINDS = new Set(["book", "article", "research-project"]);
const WORK_KINDS = new Set(["chapter", "paper"]);

function projectsRoot(): string {
  return path.join(projectRoot(runtimeConfig().corpusRoot), "projects");
}

function projectPath(projectId: string): string {
  return path.join(projectsRoot(), projectId, "project.json");
}

function readProject(projectId: string): Record<string, any> {
  if (!PAPER_ID_RE.test(projectId)) {
    throw new StoreError("invalid_project_id", "Project IDs use lowercase letters, numbers, and hyphens.");
  }
  const file = projectPath(projectId);
  if (!existsSync(file)) throw new StoreError("project_not_found", `Project not found: ${projectId}`);
  const project = readJsonFile(file);
  if (!project || typeof project !== "object") {
    throw new StoreError("project_manifest_invalid", `Project manifest is unreadable: ${projectId}`);
  }
  return project;
}

function writeProject(projectId: string, project: Record<string, unknown>): void {
  const file = projectPath(projectId);
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, `${JSON.stringify(project, null, 2)}\n`, "utf8");
}

class StoreError extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

function listProjects(): Array<Record<string, any>> {
  const root = projectsRoot();
  if (!existsSync(root)) return [];
  const projects: Array<Record<string, any>> = [];
  for (const entry of readdirSync(root, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    if (!entry.isDirectory()) continue;
    const project = readJsonFile(path.join(root, entry.name, "project.json"));
    if (project) projects.push(project);
  }
  return projects;
}

function createProject(args: {
  project_id: string;
  title: string;
  question?: string;
  kind?: string;
}): Record<string, unknown> {
  const projectId = args.project_id;
  if (!PAPER_ID_RE.test(projectId) || projectId.length > 55) {
    throw new StoreError(
      "invalid_project_id",
      "Project IDs use lowercase letters, numbers, and hyphens and leave room for the shared source-library suffix.",
    );
  }
  const kind = args.kind ?? "research-project";
  if (!PROJECT_KINDS.has(kind)) {
    throw new StoreError("invalid_project_kind", "Project kind must be book, article, or research-project.");
  }
  if (existsSync(projectPath(projectId))) {
    throw new StoreError("project_exists", `Project already exists: ${projectId}`);
  }
  const sourceWorkspaceId = `${projectId}-sources`;
  createPaper({
    paper_id: sourceWorkspaceId,
    title: `${args.title} — shared source library`,
    question: args.question ?? "",
  });
  const source = readPaper(sourceWorkspaceId);
  source.workspace_role = "shared-source-library";
  source.project_id = projectId;
  writePaper(sourceWorkspaceId, source);

  const project = {
    id: projectId,
    title: args.title,
    question: args.question ?? "",
    kind,
    source_workspace_id: sourceWorkspaceId,
    works: [],
  };
  writeProject(projectId, project);
  return { status: "ok", project, path: projectPath(projectId) };
}

function createWork(args: {
  project_id: string;
  work_id: string;
  title: string;
  question?: string;
  kind?: string;
  minimum_primary?: number;
  minimum_secondary?: number;
}): Record<string, unknown> {
  const project = readProject(args.project_id);
  const workId = args.work_id;
  if (!PAPER_ID_RE.test(workId)) {
    throw new StoreError("invalid_work_id", "Work IDs use lowercase letters, numbers, and hyphens.");
  }
  const kind = args.kind ?? (project.kind === "book" ? "chapter" : "paper");
  if (!WORK_KINDS.has(kind)) {
    throw new StoreError("invalid_work_kind", "Work kind must be chapter or paper.");
  }
  if (project.kind === "book" && kind !== "chapter") {
    throw new StoreError("book_requires_chapter", "Works in a book project must be chapters.");
  }
  createPaper({
    paper_id: workId,
    title: args.title,
    question: args.question ?? "",
    minimum_primary: args.minimum_primary ?? 1,
    minimum_secondary: args.minimum_secondary ?? 1,
  });
  const work = readPaper(workId);
  work.project_id = project.id;
  work.work_kind = kind;
  work.source_workspace_id = project.source_workspace_id;
  writePaper(workId, work);
  project.works = Array.isArray(project.works) ? project.works : [];
  project.works.push({ id: workId, title: work.title, question: work.question, kind });
  writeProject(project.id, project);
  return { status: "ok", project_id: project.id, work, path: path.join(projectRoot(runtimeConfig().corpusRoot), "papers", workId, "paper.json") };
}

function activate(args: { project_id: string; work_id: string; confirmed?: boolean }): Record<string, unknown> {
  if (!args.confirmed) {
    throw new StoreError(
      "workspace_switch_needs_confirmation",
      "Confirm the project/work switch before changing the active workspace.",
    );
  }
  const project = readProject(args.project_id);
  if (!Array.isArray(project.works) || !project.works.some((work: any) => work.id === args.work_id)) {
    throw new StoreError("work_not_in_project", "The requested work does not belong to this project.");
  }
  usePaper(args.work_id, true);
  const workspace = { project_id: project.id, work_id: args.work_id };
  const file = path.join(projectRoot(runtimeConfig().corpusRoot), ".shutong", "active-workspace.json");
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, `${JSON.stringify(workspace, null, 2)}\n`, "utf8");
  return { status: "ok", active: workspace };
}

function planSwitch(args: { query?: string }): Record<string, unknown> {
  const query = String(args.query ?? "").trim();
  if (!query) {
    throw new StoreError("empty_workspace_query", "Workspace planning requires the scholar's new question or request.");
  }
  const queryWords = new Set(query.toLocaleLowerCase().match(/[\p{L}\p{N}_]+/gu) ?? []);
  const candidates: Array<Record<string, unknown>> = [];
  for (const project of listProjects()) {
    for (const work of project.works ?? []) {
      const haystack = [
        project.id,
        project.title,
        project.question ?? "",
        work.id,
        work.title,
        work.question ?? "",
      ]
        .join(" ")
        .toLocaleLowerCase();
      const words = new Set(haystack.match(/[\p{L}\p{N}_]+/gu) ?? []);
      let score = [...queryWords].filter((word) => words.has(word)).length;
      if (query.toLocaleLowerCase().includes(work.id) || query.toLocaleLowerCase().includes(project.id)) {
        score += 100;
      }
      if (score) {
        candidates.push({
          project_id: project.id,
          project_title: project.title,
          work_id: work.id,
          work_title: work.title,
          score,
        });
      }
    }
  }
  candidates.sort(
    (a, b) =>
      Number(b.score) - Number(a.score) ||
      String(a.project_id).localeCompare(String(b.project_id)) ||
      String(a.work_id).localeCompare(String(b.work_id)),
  );
  const current = activeWorkspace(runtimeConfig().corpusRoot);
  const recommended = candidates[0] ?? null;
  const action =
    recommended && current && recommended.project_id === current.project_id && recommended.work_id === current.work_id
      ? "continue"
      : recommended
        ? "confirm_switch"
        : "create_project_or_work";
  return {
    status: "needs_scholar_confirmation",
    query,
    active: current,
    action,
    recommended,
    candidates: candidates.slice(0, 5),
    message: "This planner never changes the active workspace; ask the scholar to confirm the recommended action.",
  };
}

export async function handleWorkspace(args: {
  action?: string;
  paper_id?: string;
  title?: string;
  question?: string;
  project_id?: string;
  work_id?: string;
  kind?: string;
  query?: string;
  confirmed?: boolean;
  minimum_primary?: number;
  minimum_secondary?: number;
}): Promise<Record<string, unknown>> {
  try {
    switch (args.action ?? "list") {
      case "list":
        return {
          status: "ok",
          active: activeWorkspace(runtimeConfig().corpusRoot),
          projects: listProjects(),
        };
      case "create_paper":
        if (!args.paper_id || !args.title) {
          return { status: "error", error_code: "invalid_input", message: "paper_id and title are required." };
        }
        return createPaper({
          paper_id: args.paper_id,
          title: args.title,
          question: args.question,
          minimum_primary: args.minimum_primary,
          minimum_secondary: args.minimum_secondary,
        });
      case "create_project":
        if (!args.project_id || !args.title) {
          return { status: "error", error_code: "invalid_input", message: "project_id and title are required." };
        }
        return createProject({
          project_id: args.project_id,
          title: args.title,
          question: args.question,
          kind: args.kind,
        });
      case "create_work":
        if (!args.project_id || !args.work_id || !args.title) {
          return {
            status: "error",
            error_code: "invalid_input",
            message: "project_id, work_id, and title are required.",
          };
        }
        return createWork({
          project_id: args.project_id,
          work_id: args.work_id,
          title: args.title,
          question: args.question,
          kind: args.kind,
          minimum_primary: args.minimum_primary,
          minimum_secondary: args.minimum_secondary,
        });
      case "activate":
        if (!args.project_id || !args.work_id) {
          return { status: "error", error_code: "invalid_input", message: "project_id and work_id are required." };
        }
        return activate({ project_id: args.project_id, work_id: args.work_id, confirmed: args.confirmed });
      case "plan_switch":
        return planSwitch({ query: args.query });
      default:
        return {
          status: "error",
          error_code: "invalid_action",
          message: `Unknown workspace action: ${args.action ?? ""}`,
        };
    }
  } catch (error) {
    const failure = error as StoreError;
    return {
      status: "error",
      error_code: failure.code ?? "workspace_error",
      message: failure.message,
    };
  }
}
