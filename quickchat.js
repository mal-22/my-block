const supabase = supabase.createClient("YOUR_URL", "YOUR_PUBLIC_KEY");

supabase
  .channel('online-users')
  .on('postgres_changes',
      { event: '*', schema: 'public', table: 'profiles' },
      payload => {
          loadOnlineUsers();
      }
  )
  .subscribe();

async function loadOnlineUsers() {
  const { data } = await supabase
      .from('profiles')
      .select('*')
      .eq('online', true);

  document.getElementById("online-users").innerHTML =
      data.map(u => `<div>${u.name}</div>`).join("");
}
