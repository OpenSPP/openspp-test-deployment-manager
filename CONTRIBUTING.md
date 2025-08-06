# Contributing to OpenSPP Deployment Manager

Thank you for your interest in contributing to the OpenSPP Deployment Manager! This document provides guidelines and instructions for contributing to the project.

## Code of Conduct

By participating in this project, you agree to abide by our Code of Conduct: be respectful, inclusive, and constructive in all interactions.

## How to Contribute

### Reporting Issues

- Check if the issue already exists in the [Issues](https://github.com/OpenSPP/openspp-deployment-manager/issues) section
- Provide a clear description of the problem
- Include steps to reproduce the issue
- Mention your environment (OS, Python version, Docker version)
- Include relevant logs or error messages

### Suggesting Features

- Open an issue with the "enhancement" label
- Describe the feature and its use case
- Explain why this feature would be useful to other users

### Submitting Pull Requests

1. **Fork the Repository**
   ```bash
   git clone https://github.com/OpenSPP/openspp-deployment-manager.git
   cd openspp-deployment-manager
   ```

2. **Create a Feature Branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

3. **Set Up Development Environment**
   ```bash
   # Install uv if not already installed
   curl -LsSf https://astral.sh/uv/install.sh | sh
   
   # Install dependencies
   uv sync --all-extras
   ```

4. **Make Your Changes**
   - Follow the existing code style and patterns
   - Add comments for complex logic
   - Update documentation if needed
   - Add tests for new functionality

5. **Run Tests**
   ```bash
   # Run all tests
   uv run pytest
   
   # Run specific test file
   uv run pytest tests/test_deployment_manager.py
   ```

6. **Commit Your Changes**
   ```bash
   git add .
   git commit -m "feat: add new feature description"
   ```
   
   Follow [Conventional Commits](https://www.conventionalcommits.org/) format:
   - `feat:` for new features
   - `fix:` for bug fixes
   - `docs:` for documentation changes
   - `test:` for test additions/changes
   - `refactor:` for code refactoring
   - `chore:` for maintenance tasks

7. **Push and Create Pull Request**
   ```bash
   git push origin feature/your-feature-name
   ```
   Then create a pull request on GitHub.

## Development Guidelines

### Code Style

- Follow PEP 8 for Python code
- Use meaningful variable and function names
- Keep functions focused and small
- Add docstrings to functions and classes
- Use type hints where appropriate

### Testing

- Write tests for new functionality
- Ensure all tests pass before submitting PR
- Aim for good test coverage
- Use pytest fixtures for test setup

### Documentation

- Update README.md if adding new features
- Document configuration options
- Include examples for complex features
- Keep documentation clear and concise

### Security Considerations

⚠️ **Important Security Notes:**

- **Never** add authentication/authorization to this tool - it's designed for internal use only
- **Never** expose this application to the public internet
- Always validate and sanitize user inputs
- Use subprocess with list arguments, not shell=True
- Don't commit secrets or credentials
- Review security warnings in README.md

### Project Structure

```
openspp-deployment-manager/
├── src/                    # Core application modules
│   ├── deployment_manager.py
│   ├── docker_handler.py
│   ├── database.py
│   └── utils.py
├── templates/              # Configuration templates
├── tests/                  # Test files
├── app.py                  # Streamlit web interface
└── config.yaml.example     # Configuration example
```

## Questions or Need Help?

- Open an issue for questions
- Join the OpenSPP community discussions
- Check existing documentation and issues first

## License

By contributing to this project, you agree that your contributions will be licensed under the Apache 2.0 License.