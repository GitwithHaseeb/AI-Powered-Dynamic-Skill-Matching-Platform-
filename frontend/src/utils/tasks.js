/** Strict match: task is assigned to the logged-in user (by id, then email, then display name). */
export function taskAssignedToUser(task, user) {
  if (!user || !task) return false;
  if (task.is_assigned_to_me === true) return true;
  if (task.is_assigned_to_me === false) return false;
  const uid = String(user.id ?? user._id ?? '').trim();
  const aid = String(task.assigned_to ?? '').trim();
  if (uid && aid && uid === aid) return true;
  const userEmail = String(user.email ?? '').trim().toLowerCase();
  if (userEmail && aid.toLowerCase() === userEmail) return true;
  const userName = String(user.username ?? user.name ?? user.full_name ?? '').trim();
  if (userName && aid === userName) return true;
  return false;
}
