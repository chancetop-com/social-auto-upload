# PowerShell examples for the installed sau CLI.

# account_name is user-defined. Each local account alias selects a persistent browser profile.
# You can prepare multiple account names and run them in parallel.
$account = "account_a"
$video = "videos/demo.mp4"
$thumbnail = "videos/demo.png"
$noteImages = @("videos/demo1.png", "videos/demo2.png")

sau xiaohongshu login --account $account --headless
sau xiaohongshu check --account $account

sau xiaohongshu upload-video `
  --account $account `
  --file $video `
  --title "Xiaohongshu video from PowerShell" `
  --desc "Xiaohongshu video description from PowerShell #cli #video" `
  --thumbnail $thumbnail `
  --headless

sau xiaohongshu upload-note `
  --account $account `
  --images $noteImages `
  --title "Xiaohongshu note title from PowerShell" `
  --note "Xiaohongshu note from PowerShell #cli #note" `
  --headless
