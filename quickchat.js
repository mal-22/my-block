//const supabase = supabase.createClient("YOUR_URL", "YOUR_PUBLIC_KEY");
//
//supabase
//  .channel('online-users')
//  .on('postgres_changes',
//      { event: '*', schema: 'public', table: 'profiles' },
//      payload => {
//          loadOnlineUsers();
//      }
//  )
//  .subscribe();
//
//async function loadOnlineUsers() {
//  const { data } = await supabase
//      .from('profiles')
//      .select('*')
//      .eq('online', true);
//
//  document.getElementById("online-users").innerHTML =
//      data.map(u => `<div>${u.name}</div>`).join("");
//}


// ==============================
// Current User Management
// ==============================
let currentUser = null;

// Fetch current user from API
async function fetchCurrentUser() {
    try {
        const response = await fetch('/api/chat/user', {
            credentials: 'include'
        });
        
        if (!response.ok) {
            if (response.status === 401) {
                console.error('❌ Not authenticated, redirecting to login');
                window.location.href = '/login';
                return null;
            }
            throw new Error(`HTTP ${response.status}`);
        }
        
        currentUser = await response.json();
        console.log('✅ Current user loaded:', currentUser);
        return currentUser;
        
    } catch (error) {
        console.error('❌ Error fetching current user:', error);
        // Redirect to login on any error
        window.location.href = '/login';
        return null;
    }
}

// ==============================
// Initialize App
// ==============================
async function initApp() {
    console.log('🚀 Initializing QuickChat app...');
    
    // First, ensure we have the current user
    const user = await fetchCurrentUser();
    if (!user) {
        console.error('❌ Failed to get current user, stopping initialization');
        return;
    }
    
    console.log('✅ App initialized with user:', user.username);
    
    // Now load other online users
    fetchUsers();
    
    // Refresh user list periodically
    setInterval(fetchUsers, 5000);
}

// ==============================
// Start App on Page Load
// ==============================
document.addEventListener('DOMContentLoaded', initApp);
