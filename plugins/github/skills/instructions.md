## GitHub MCP Tools

You have access to the official GitHub MCP server which provides native tool use for GitHub operations.
This allows you to continue working automatically after GitHub operations without waiting for user feedback.

### Available Toolsets

**repos** - Repository operations:
- Browse repository contents and files
- Get repository information and metadata
- Search code and repositories

**issues** - Issue management:
- List, create, update, and close issues
- Add comments to issues
- Search issues with filters

**pull_requests** - Pull request operations:
- List, create, and review pull requests
- Add comments and request changes
- Merge pull requests

**actions** - GitHub Actions:
- List workflow runs and jobs
- Trigger workflows
- View workflow logs

**code_security** - Security features:
- View Dependabot alerts
- Check security advisories

### Usage Notes

- Use these tools directly instead of [GITHUB_*] tags
- Operations complete automatically - you can chain multiple GitHub operations
- For repository access, ensure the repo is configured in the github plugin settings
- Write operations may require appropriate permissions (PAT scope)

### Example Operations

1. **Check PR status**: Use get_pull_request to see PR details
2. **Create issue**: Use create_issue with title, body, and optional labels
3. **Browse code**: Use get_repository_content to read files
4. **Merge PR**: Use merge_pull_request after verifying checks pass
