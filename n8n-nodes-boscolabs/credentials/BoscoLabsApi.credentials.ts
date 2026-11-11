import type {
	IAuthenticateGeneric,
	Icon,
	ICredentialTestRequest,
	ICredentialType,
	INodeProperties,
} from 'n8n-workflow';

export class BoscoLabsApi implements ICredentialType {
	name = 'boscoLabsApi';

	displayName = 'Bosco Labs API';

	icon: Icon = { light: 'file:../icons/boscolabs.svg', dark: 'file:../icons/boscolabs.dark.svg' };

	documentationUrl = 'https://boscolabs.dev/api.html';

	properties: INodeProperties[] = [
		{
			displayName: 'API Key',
			name: 'apiKey',
			type: 'string',
			typeOptions: { password: true },
			required: true,
			default: '',
			placeholder: 'e.g. bl_live_...',
			description:
				'Your Bosco Labs API key (prepaid credits). Get one at <a href="https://boscolabs.dev/api.html#key" target="_blank">boscolabs.dev/api.html</a>. The credential test reads your balance and costs nothing.',
		},
	];

	authenticate: IAuthenticateGeneric = {
		type: 'generic',
		properties: {
			headers: {
				Authorization: '=Bearer {{$credentials.apiKey}}',
			},
		},
	};

	test: ICredentialTestRequest = {
		request: {
			baseURL: 'https://api.boscolabs.dev',
			url: '/v1/me',
			method: 'GET',
		},
	};
}
