import { useMembers, type WorkspaceRole } from './use-members';
import { useAuth } from './use-auth';

const LEVELS: Record<WorkspaceRole, number> = { viewer: 0, member: 1, admin: 2, owner: 3 };

/**
 * Papel do usuário atual no workspace corrente (RBAC-FE-001). Usado para NÃO
 * mostrar ações que o backend recusaria com 403 — o servidor continua sendo a
 * autoridade; isto é só experiência de usuário.
 */
export function useWorkspaceRole() {
  const { members } = useMembers();
  const { user } = useAuth();
  const role: WorkspaceRole = members.find((m) => m.user_id === user?.id)?.role ?? 'viewer';
  const level = LEVELS[role] ?? 0;
  return {
    role,
    canWrite: level >= LEVELS.member,   // viewer não escreve
    isAdmin: level >= LEVELS.admin,
    isOwner: level >= LEVELS.owner,
  };
}
